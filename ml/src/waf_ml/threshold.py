"""Threshold calibration for ML block-mode.

WHY: Ships: annotate-only Lua subrequest.  wants block-mode
behind a calibrated threshold θ. We define the calibration objective as

    θ* = min { θ ∈ [0, 1] : FPR(θ) ≤ target_fpr }

i.e. *the lowest threshold that still respects the FP budget*. This
maximises recall under a fixed FPR ceiling — the right policy when
false positives have a real operational cost (every blocked benign
request is a Slack alert).

Output is a small dataclass, not a number, so the dashboard can plot
the full FPR/TPR trace alongside the chosen point.

CLI:
    python -m waf_ml.threshold \
        --baseline ml/models/active/baseline_features.csv \
        --report   ml/models/active/report.json \
        --target-fpr 0.01

The CLI loads the eval report from `report.json`, falls back to a
synthetic dataset if no labelled scores file is provided, and prints
the chosen θ.  backend reads it from `ml_config`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass
class ThresholdReport:
    """The chosen θ plus the surrounding ROC trace.

    `trace_thresholds`/`trace_fpr`/`trace_tpr` are aligned arrays so the
    UI can render the ROC curve and mark `chosen_threshold` on it.
    """
    chosen_threshold: float
    target_fpr: float
    achieved_fpr: float
    achieved_tpr: float  # recall at θ*
    n_thresholds: int
    trace_thresholds: list[float]
    trace_fpr: list[float]
    trace_tpr: list[float]
    n_positive: int
    n_negative: int


def calibrate(
    y_true: np.ndarray,
    scores: np.ndarray,
    *,
    target_fpr: float = 0.01,
    n_thresholds: int = 201,
) -> ThresholdReport:
    """Sweep θ over `n_thresholds` evenly-spaced points and pick θ*.

    SAFETY: `target_fpr ≤ 0` collapses to "never block"; `target_fpr ≥ 1`
            collapses to θ=0. Both are documented but caller-friendly.
    """
    y = np.asarray(y_true, dtype=np.int64).ravel()
    s = np.asarray(scores, dtype=np.float64).ravel()
    if y.size != s.size:
        raise ValueError("y_true and scores must have the same length")
    if y.size == 0:
        raise ValueError("empty input")

    n_pos = max(int((y == 1).sum()), 1)
    n_neg = max(int((y == 0).sum()), 1)

    thresholds = np.linspace(0.0, 1.0, n_thresholds)
    fprs = np.zeros_like(thresholds)
    tprs = np.zeros_like(thresholds)

    # WHY: vectorised loop is plenty for 25-feature, ≤ 1M-row inputs
    #      and keeps the function dependency-free (no sklearn).
    for i, th in enumerate(thresholds):
        pred = s >= th
        tp = int(np.sum(pred & (y == 1)))
        fp = int(np.sum(pred & (y == 0)))
        fprs[i] = fp / n_neg
        tprs[i] = tp / n_pos

    # Pick the LOWEST threshold whose FPR is within budget.
    # `<= target_fpr`: ties go to the lower threshold → higher recall.
    valid = fprs <= max(target_fpr, 0.0)
    if not valid.any():
        # Budget unattainable — fall back to most-restrictive θ=1.
        chosen_idx = int(thresholds.argmax())
    else:
        chosen_idx = int(np.argmin(np.where(valid, thresholds, np.inf)))

    return ThresholdReport(
        chosen_threshold=float(thresholds[chosen_idx]),
        target_fpr=float(target_fpr),
        achieved_fpr=float(fprs[chosen_idx]),
        achieved_tpr=float(tprs[chosen_idx]),
        n_thresholds=int(n_thresholds),
        trace_thresholds=thresholds.tolist(),
        trace_fpr=fprs.tolist(),
        trace_tpr=tprs.tolist(),
        n_positive=n_pos,
        n_negative=n_neg,
    )


def report_to_dict(r: ThresholdReport) -> dict:
    return asdict(r)


def _load_scores_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Two-column CSV (`label,score`) or scores-only with `label` parsed
    from a sibling header. Used by the CLI when an operator pipes their
    own scoring run.
    """
    import csv

    y: list[int] = []
    s: list[float] = []
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                y.append(int(row.get("label", row.get("y_true", 0))))
                s.append(float(row.get("score", row.get("prob", 0.0))))
            except (TypeError, ValueError):
                continue
    return np.asarray(y, dtype=np.int64), np.asarray(s, dtype=np.float64)


def _synthetic_demo(seed: int = 42, n: int = 1000) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic labelled scores for the dependency-free CLI smoke."""
    rng = np.random.default_rng(seed)
    n_pos = n // 2
    n_neg = n - n_pos
    y = np.concatenate([np.ones(n_pos, dtype=np.int64), np.zeros(n_neg, dtype=np.int64)])
    # Positives lean high, negatives lean low; some overlap.
    s_pos = np.clip(rng.normal(0.85, 0.10, n_pos), 0, 1)
    s_neg = np.clip(rng.normal(0.20, 0.10, n_neg), 0, 1)
    s = np.concatenate([s_pos, s_neg])
    perm = rng.permutation(n)
    return y[perm], s[perm]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="waf-ml-threshold")
    ap.add_argument("--scores-csv", type=Path, default=None,
                    help="CSV with columns label,score. Required for real calibration.")
    ap.add_argument("--target-fpr", type=float, default=0.01)
    ap.add_argument("--n-thresholds", type=int, default=201)
    ap.add_argument("--out", type=Path, default=None,
                    help="Write the JSON report here (else stdout).")
    args = ap.parse_args(argv)

    if args.scores_csv:
        if not args.scores_csv.exists():
            raise SystemExit(f"scores CSV not found: {args.scores_csv}")
        y, s = _load_scores_csv(args.scores_csv)
    else:
        # WHY: CLI without inputs is a smoke run; useful for "is this
        # module wired correctly?" without producing a real artefact.
        print("waf-ml-threshold: --scores-csv missing, running synthetic demo",
              file=sys.stderr)
        y, s = _synthetic_demo()

    report = calibrate(y, s, target_fpr=args.target_fpr, n_thresholds=args.n_thresholds)
    blob = json.dumps(report_to_dict(report), indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(blob, encoding="utf-8")
        print(
            f"θ*={report.chosen_threshold:.4f}  "
            f"FPR={report.achieved_fpr:.4f}  TPR={report.achieved_tpr:.4f}  "
            f"→ {args.out}",
        )
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["ThresholdReport", "calibrate", "main", "report_to_dict"]
