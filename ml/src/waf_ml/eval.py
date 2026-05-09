"""Evaluation report — same shape for every model so they're comparable."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass
class EvalReport:
    model: str
    trained_at: str
    dataset: str
    n_train: int
    n_test: int
    metrics: dict[str, float]
    confusion_matrix: dict[str, int]
    thresholds: dict[str, float]
    # WHY: a single split gives one number; CP-2 wants stability proof.
    #      `metrics_cv` carries mean ± std over K stratified folds;
    #      empty dict for unsupervised models (IsolationForest).
    metrics_cv: dict[str, dict[str, float]] | None = field(default=None)


def _fpr_at_recall(
    y_true: np.ndarray, scores: np.ndarray, target_recall: float,
) -> tuple[float, float]:
    """Return (fpr, threshold) at the lowest threshold that still hits target recall."""
    order = np.argsort(scores)[::-1]
    y_sorted = y_true[order]
    s_sorted = scores[order]
    p = max(int(y_true.sum()), 1)
    n = max(int((1 - y_true).sum()), 1)
    tp = 0
    fp = 0
    best_threshold = 0.0
    best_fpr = 1.0
    for i in range(len(y_sorted)):
        if y_sorted[i] == 1:
            tp += 1
        else:
            fp += 1
        if tp / p >= target_recall:
            best_threshold = float(s_sorted[i])
            best_fpr = fp / n
            break
    return best_fpr, best_threshold


def _threshold_at_recall(y_true: np.ndarray, scores: np.ndarray, target: float) -> float:
    """Lowest threshold whose recall is at least `target`."""
    _, t = _fpr_at_recall(y_true, scores, target)
    return t


def evaluate(
    *,
    model_name: str,
    dataset: str,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    scores: np.ndarray,
    n_train: int,
    n_test: int,
) -> EvalReport:
    """Return a report dict identical in shape across models.

    NOTE: `scores` is a probability-like float per row; for IsolationForest
          we pass the negative of `decision_function` re-scaled to [0, 1].
    """
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = int(cm[0][0]), int(cm[0][1]), int(cm[1][0]), int(cm[1][1])

    fpr099, thr099 = _fpr_at_recall(y_true, scores, 0.99)
    thr090 = _threshold_at_recall(y_true, scores, 0.90)

    try:
        auc = float(roc_auc_score(y_true, scores))
    except ValueError:
        auc = float("nan")

    return EvalReport(
        model=model_name,
        trained_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        dataset=dataset,
        n_train=int(n_train),
        n_test=int(n_test),
        metrics={
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "f1": float(f1_score(y_true, y_pred, zero_division=0)),
            "roc_auc": auc,
            "fpr_at_recall_0_99": float(fpr099),
        },
        confusion_matrix={"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        thresholds={
            "recall_0_90": float(thr090),
            "recall_0_99": float(thr099),
        },
    )


def report_to_dict(r: EvalReport) -> dict[str, Any]:
    return asdict(r)


__all__ = ["EvalReport", "evaluate", "report_to_dict"]
