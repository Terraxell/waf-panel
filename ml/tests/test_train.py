"""Smoke-train all three models on synthetic data.

WHY: catches silent breakage in the train_all wiring (a missing artefact,
     a stale eval, an unexpected report shape) without depending on
     CSIC / CICIDS being downloaded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from waf_ml.train import HAS_XGB, train_all


@pytest.fixture
def tiny_run(tmp_path: Path):
    """One synthetic-data train cycle, capped small so CI stays under a second."""
    out = tmp_path / "v_test"
    # Patch the synthetic generator down to 200 rows for CI speed.
    from waf_ml import datasets
    original = datasets.generate_synthetic
    datasets.generate_synthetic = lambda n=200, seed=42, ratio_malicious=0.4: original(
        n=200, seed=seed, ratio_malicious=ratio_malicious,
    )
    try:
        outs = train_all(dataset="synthetic", out_dir=out, seed=7)
        yield out, outs
    finally:
        datasets.generate_synthetic = original


def test_artifacts_written(tiny_run):
    out_dir, outs = tiny_run
    assert out_dir.is_dir()
    expected = {"lr.pkl", "lr.json", "iforest.pkl", "iforest.json", "report.json"}
    if HAS_XGB:
        expected |= {"xgboost.pkl", "xgboost.json"}
    on_disk = {p.name for p in out_dir.iterdir()}
    assert expected <= on_disk


def test_each_model_returns_a_report(tiny_run):
    _, outs = tiny_run
    names = {o.model_name for o in outs}
    assert "lr" in names and "iforest" in names
    if HAS_XGB:
        assert "xgboost" in names
    for o in outs:
        m = o.report.metrics
        assert 0.0 <= m["precision"] <= 1.0
        assert 0.0 <= m["recall"] <= 1.0
        assert 0.0 <= m["f1"] <= 1.0


def test_combined_report_keyed_by_model(tiny_run):
    out_dir, outs = tiny_run
    combined = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    for o in outs:
        assert o.model_name in combined
        assert "metrics" in combined[o.model_name]


def test_lr_and_xgb_beat_random(tiny_run):
    """Sanity: a supervised model on labelled data should be better than 0.5 AUC."""
    _, outs = tiny_run
    for o in outs:
        if o.model_name in {"lr", "xgboost"}:
            assert o.report.metrics["roc_auc"] > 0.6, (
                f"{o.model_name} ROC-AUC={o.report.metrics['roc_auc']} too low"
            )


def test_supervised_models_carry_cv_metrics(tiny_run):
    """Every supervised model gets a metrics_cv block; IF stays empty."""
    _, outs = tiny_run
    for o in outs:
        if o.model_name in {"lr", "xgboost"}:
            assert o.report.metrics_cv is not None, f"{o.model_name} missing CV"
            for metric in ("precision", "recall", "f1", "roc_auc"):
                assert metric in o.report.metrics_cv
                cell = o.report.metrics_cv[metric]
                assert {"mean", "std"} <= set(cell.keys())
                assert 0.0 <= cell["mean"] <= 1.0
                assert cell["std"] >= 0.0
        elif o.model_name == "iforest":
            # SAFETY: IF is unsupervised, sklearn scoring layer rejects it.
            assert o.report.metrics_cv in (None, {}), (
                f"iforest unexpectedly carries CV: {o.report.metrics_cv}"
            )
