"""EvalReport shape correctness — the JSON contract that lands in ml_models."""

from __future__ import annotations

import numpy as np
import pytest

from waf_ml.eval import EvalReport, evaluate, report_to_dict


def _toy_arrays():
    # 6 items, 3 of each class. Scores roughly track labels with one mistake
    # so we get realistic-looking precision/recall numbers.
    y_true = np.array([0, 0, 0, 1, 1, 1])
    y_pred = np.array([0, 0, 1, 1, 1, 0])  # 1 FP, 1 FN
    scores = np.array([0.10, 0.20, 0.55, 0.80, 0.90, 0.45])
    return y_true, y_pred, scores


def test_evaluate_returns_dataclass():
    y_true, y_pred, scores = _toy_arrays()
    r = evaluate(
        model_name="lr", dataset="synthetic-v1",
        y_true=y_true, y_pred=y_pred, scores=scores,
        n_train=24, n_test=6,
    )
    assert isinstance(r, EvalReport)
    assert r.model == "lr"
    assert r.dataset == "synthetic-v1"
    assert r.n_train == 24 and r.n_test == 6


def test_metrics_keys():
    y_true, y_pred, scores = _toy_arrays()
    r = evaluate(
        model_name="xgboost", dataset="synthetic-v1",
        y_true=y_true, y_pred=y_pred, scores=scores,
        n_train=24, n_test=6,
    )
    assert set(r.metrics.keys()) == {
        "precision", "recall", "f1", "roc_auc", "fpr_at_recall_0_99",
    }
    for k, v in r.metrics.items():
        assert isinstance(v, float), f"{k} is not float"
    assert 0.0 <= r.metrics["precision"] <= 1.0
    assert 0.0 <= r.metrics["recall"] <= 1.0


def test_confusion_matrix_shape():
    y_true, y_pred, scores = _toy_arrays()
    r = evaluate(
        model_name="lr", dataset="synthetic-v1",
        y_true=y_true, y_pred=y_pred, scores=scores,
        n_train=24, n_test=6,
    )
    assert set(r.confusion_matrix.keys()) == {"tn", "fp", "fn", "tp"}
    total = sum(r.confusion_matrix.values())
    assert total == len(y_true)


def test_thresholds_are_floats():
    y_true, y_pred, scores = _toy_arrays()
    r = evaluate(
        model_name="iforest", dataset="synthetic-v1",
        y_true=y_true, y_pred=y_pred, scores=scores,
        n_train=24, n_test=6,
    )
    assert set(r.thresholds.keys()) == {"recall_0_90", "recall_0_99"}
    assert all(isinstance(v, float) for v in r.thresholds.values())


def test_report_to_dict_is_jsonable():
    """The report must serialise cleanly because we INSERT it as jsonb."""
    import json
    y_true, y_pred, scores = _toy_arrays()
    r = evaluate(
        model_name="lr", dataset="synthetic-v1",
        y_true=y_true, y_pred=y_pred, scores=scores,
        n_train=24, n_test=6,
    )
    d = report_to_dict(r)
    # Must round-trip through json.
    json.dumps(d)
    # And expose top-level keys the registry / dashboard expect.
    assert {"model", "trained_at", "dataset", "metrics", "confusion_matrix"} <= set(d.keys())


def test_perfect_predictions():
    y_true = np.array([0, 0, 1, 1])
    y_pred = np.array([0, 0, 1, 1])
    scores = np.array([0.05, 0.10, 0.95, 0.99])
    r = evaluate(
        model_name="lr", dataset="synthetic-v1",
        y_true=y_true, y_pred=y_pred, scores=scores,
        n_train=10, n_test=4,
    )
    assert r.metrics["precision"] == pytest.approx(1.0)
    assert r.metrics["recall"] == pytest.approx(1.0)
    assert r.metrics["f1"] == pytest.approx(1.0)
    assert r.metrics["roc_auc"] == pytest.approx(1.0)
    assert r.confusion_matrix == {"tn": 2, "fp": 0, "fn": 0, "tp": 2}
