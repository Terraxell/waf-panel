"""Threshold calibration — invariants and FPR-budget compliance."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from waf_ml.threshold import ThresholdReport, calibrate, main, report_to_dict


def _easy_dataset(seed: int = 0):
    """Well-separated synthetic: positives near 0.9, negatives near 0.1."""
    rng = np.random.default_rng(seed)
    n_pos, n_neg = 500, 500
    s_pos = np.clip(rng.normal(0.9, 0.05, n_pos), 0, 1)
    s_neg = np.clip(rng.normal(0.1, 0.05, n_neg), 0, 1)
    y = np.concatenate([np.ones(n_pos, dtype=np.int64), np.zeros(n_neg, dtype=np.int64)])
    s = np.concatenate([s_pos, s_neg])
    perm = rng.permutation(len(y))
    return y[perm], s[perm]


def _hard_dataset(seed: int = 1):
    """Heavily overlapping — used to test FPR-budget unattainable case."""
    rng = np.random.default_rng(seed)
    n = 200
    y = rng.integers(0, 2, n).astype(np.int64)
    # Scores are pure noise — model has no signal whatsoever.
    s = rng.uniform(0.0, 1.0, n)
    return y, s


def test_calibrate_returns_report_with_aligned_traces():
    y, s = _easy_dataset()
    r = calibrate(y, s, target_fpr=0.01)
    assert isinstance(r, ThresholdReport)
    assert len(r.trace_thresholds) == r.n_thresholds
    assert len(r.trace_fpr) == r.n_thresholds
    assert len(r.trace_tpr) == r.n_thresholds


def test_chosen_threshold_respects_fpr_budget():
    y, s = _easy_dataset()
    r = calibrate(y, s, target_fpr=0.01)
    # SAFETY: this is THE contract — the chosen θ must satisfy the budget.
    assert r.achieved_fpr <= 0.01 + 1e-9
    # And achieve real recall on a well-separated dataset.
    assert r.achieved_tpr > 0.9


def test_lower_target_fpr_gives_higher_threshold():
    """Tightening the budget pushes θ up (fewer false positives)."""
    y, s = _easy_dataset()
    r_loose = calibrate(y, s, target_fpr=0.10)
    r_tight = calibrate(y, s, target_fpr=0.001)
    assert r_tight.chosen_threshold >= r_loose.chosen_threshold


def test_fpr_trace_is_monotonic_non_increasing():
    """FPR(θ) must not grow as θ grows. WHY: it's the same predicate."""
    y, s = _easy_dataset()
    r = calibrate(y, s, target_fpr=0.05, n_thresholds=51)
    fpr = np.asarray(r.trace_fpr)
    # Allow strict equality on flat regions; just no upticks.
    assert np.all(np.diff(fpr) <= 1e-12)


def test_tpr_trace_is_monotonic_non_increasing():
    y, s = _easy_dataset()
    r = calibrate(y, s, target_fpr=0.05, n_thresholds=51)
    tpr = np.asarray(r.trace_tpr)
    assert np.all(np.diff(tpr) <= 1e-12)


def test_unattainable_budget_falls_back_to_max_threshold():
    """If even θ=1 has FPR > target, the function should never crash —
    it picks the most-restrictive θ available (=1.0) and reports."""
    y, s = _hard_dataset()
    r = calibrate(y, s, target_fpr=0.0)  # impossible on real data
    assert r.chosen_threshold == pytest.approx(1.0)


def test_report_to_dict_is_json_serialisable():
    y, s = _easy_dataset()
    r = calibrate(y, s, target_fpr=0.01)
    json.dumps(report_to_dict(r))


def test_calibrate_rejects_mismatched_inputs():
    with pytest.raises(ValueError):
        calibrate(np.array([0, 1]), np.array([0.5]))


def test_calibrate_rejects_empty_inputs():
    with pytest.raises(ValueError):
        calibrate(np.array([]), np.array([]))


def test_main_synthetic_demo_writes_report(tmp_path: Path):
    out = tmp_path / "th.json"
    rc = main(["--out", str(out), "--n-thresholds", "51"])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "chosen_threshold" in payload
    assert payload["target_fpr"] == 0.01
    assert payload["achieved_fpr"] <= 0.01 + 1e-9


def test_main_loads_scores_csv(tmp_path: Path):
    """Driver path: operator pipes a real (label, score) CSV in."""
    csv = tmp_path / "scores.csv"
    rng = np.random.default_rng(2)
    n_pos, n_neg = 200, 200
    s_pos = np.clip(rng.normal(0.85, 0.05, n_pos), 0, 1)
    s_neg = np.clip(rng.normal(0.15, 0.05, n_neg), 0, 1)
    rows = ["label,score"]
    rows.extend(f"1,{x:.6f}" for x in s_pos)
    rows.extend(f"0,{x:.6f}" for x in s_neg)
    csv.write_text("\n".join(rows), encoding="utf-8")

    out = tmp_path / "th.json"
    rc = main([
        "--scores-csv", str(csv),
        "--target-fpr", "0.01",
        "--out", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["n_positive"] == n_pos
    assert payload["n_negative"] == n_neg
    assert payload["achieved_fpr"] <= 0.01 + 1e-9


def test_chosen_threshold_in_unit_interval():
    y, s = _easy_dataset()
    r = calibrate(y, s, target_fpr=0.01)
    assert 0.0 <= r.chosen_threshold <= 1.0
