"""PSI + KS drift module — invariants and threshold behaviour."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from waf_ml.drift import (
    KS_ALPHA,
    PSI_ALERT,
    PSI_WARN,
    compare_columns,
    ks_pvalue,
    main,
    psi,
)


def _seeded(rng_seed: int = 0):
    return np.random.default_rng(rng_seed)


def test_psi_is_zero_for_identical_distributions():
    rng = _seeded(0)
    a = rng.normal(size=2000)
    # Compare a sample to *itself*. PSI must be near-zero.
    assert psi(a, a) < 1e-9


def test_psi_grows_with_a_real_shift():
    rng = _seeded(1)
    base = rng.normal(loc=0.0, scale=1.0, size=2000)
    shifted = rng.normal(loc=2.0, scale=1.0, size=2000)
    score = psi(base, shifted)
    # SAFETY: a 2-sigma mean shift is unambiguously into "alert" territory.
    assert score >= PSI_ALERT


def test_psi_handles_constant_baseline_gracefully():
    """A constant-zero baseline must not divide by zero or NaN out."""
    base = np.zeros(500)
    cur = np.ones(500)
    score = psi(base, cur)
    assert np.isfinite(score)


def test_psi_handles_empty_inputs():
    assert psi(np.array([]), np.array([1.0, 2.0])) == 0.0
    assert psi(np.array([1.0]), np.array([])) == 0.0


def test_ks_pvalue_is_high_for_same_distribution():
    rng = _seeded(2)
    a = rng.normal(size=400)
    b = rng.normal(size=400)
    _, p = ks_pvalue(a, b)
    # WHY: two N(0,1) samples should not be flagged as different.
    assert p > KS_ALPHA


def test_ks_pvalue_is_low_for_clearly_different_distributions():
    rng = _seeded(3)
    a = rng.normal(loc=0.0, size=1000)
    b = rng.normal(loc=2.5, size=1000)
    stat, p = ks_pvalue(a, b)
    assert stat > 0.0
    assert p < KS_ALPHA


def test_compare_columns_levels_match_thresholds():
    rng = _seeded(4)
    base = {
        "len_url": rng.normal(loc=20, scale=5, size=2000),
        "n_special_path": rng.normal(loc=0, scale=1, size=2000),
    }
    cur = {
        "len_url": rng.normal(loc=20, scale=5, size=2000),  # clean
        "n_special_path": rng.normal(loc=4, scale=1, size=2000),  # alert
    }
    rows = {f.feature: f for f in compare_columns(base, cur)}
    assert rows["len_url"].level in {"clean", "warn"}
    assert rows["n_special_path"].level == "alert"
    # PSI on the obviously-shifted column must clear the alert threshold.
    assert rows["n_special_path"].psi >= PSI_ALERT


def test_compare_columns_skips_unmatched_columns():
    base = {"a": np.array([1.0, 2.0, 3.0, 4.0, 5.0])}
    cur = {"b": np.array([1.0, 2.0, 3.0, 4.0, 5.0])}
    out = compare_columns(base, cur)
    assert out == []


def test_psi_warn_alert_constants_are_ordered():
    # Sanity guard: if someone reorders constants, the levels stop making sense.
    assert 0 < PSI_WARN < PSI_ALERT < 1.0


def test_main_writes_report_and_returns_nonzero_on_alert(tmp_path: Path):
    baseline_csv = tmp_path / "base.csv"
    current_csv = tmp_path / "cur.csv"
    report_json = tmp_path / "drift.json"

    rng = _seeded(5)
    base_col = rng.normal(loc=0.0, scale=1.0, size=400)
    cur_col = rng.normal(loc=2.5, scale=1.0, size=400)

    baseline_csv.write_text(
        "feat\n" + "\n".join(f"{x:.4f}" for x in base_col), encoding="utf-8",
    )
    current_csv.write_text(
        "feat\n" + "\n".join(f"{x:.4f}" for x in cur_col), encoding="utf-8",
    )

    rc = main([
        "--baseline", str(baseline_csv),
        "--current", str(current_csv),
        "--report", str(report_json),
    ])
    assert rc == 2  # alert → exit code 2 (CI-friendly)
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["alert_count"] >= 1
    assert payload["features"][0]["feature"] == "feat"


def test_main_returns_zero_when_clean(tmp_path: Path):
    rng = _seeded(6)
    base_col = rng.normal(size=400)
    # Same distribution → clean.
    cur_col = rng.normal(size=400)

    base_csv = tmp_path / "b.csv"
    cur_csv = tmp_path / "c.csv"
    base_csv.write_text(
        "feat\n" + "\n".join(f"{x:.4f}" for x in base_col), encoding="utf-8",
    )
    cur_csv.write_text(
        "feat\n" + "\n".join(f"{x:.4f}" for x in cur_col), encoding="utf-8",
    )

    rc = main([
        "--baseline", str(base_csv),
        "--current", str(cur_csv),
        "--report", str(tmp_path / "r.json"),
    ])
    assert rc == 0


def test_main_errors_on_missing_files():
    with pytest.raises(SystemExit):
        main(["--baseline", "/no/such", "--current", "/no/such"])
