"""Offline trainer — three models on the same split, comparable reports.

CLI:
    python -m waf_ml.train [--dataset csic|synthetic] [--csic-path PATH]
                           [--out ml/models/<version>] [--seed 42]
                           [--register] [--activate {lr,xgboost,iforest}]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.base import clone
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split

try:
    from xgboost import XGBClassifier  # type: ignore
    HAS_XGB = True
except Exception:  # pragma: no cover - optional in tests
    XGBClassifier = None  # type: ignore[assignment]
    HAS_XGB = False

from .datasets import generate_synthetic, load_cicids_2017, load_csic_2010
from .datasets.synthetic import LabelledRequest
from .eval import EvalReport, evaluate, report_to_dict
from .features import FEATURE_COLUMNS, featurize


@dataclass
class TrainOutput:
    model_name: str
    artifact_path: Path
    report: EvalReport


def _load(
    dataset: str,
    csic_path: Path | None,
    cicids_path: Path | None,
    seed: int,
) -> tuple[list[LabelledRequest], str]:
    if dataset == "synthetic":
        return generate_synthetic(n=2000, seed=seed), "synthetic-v1"
    if dataset == "csic":
        if csic_path is None:
            raise SystemExit("--csic-path required for CSIC dataset")
        rows = load_csic_2010(csic_path)
        if not rows:
            raise SystemExit(f"no data found under {csic_path}")
        return rows, "csic-2010"
    if dataset == "cicids":
        if cicids_path is None:
            raise SystemExit("--cicids-path required for CICIDS dataset")
        rows = load_cicids_2017(cicids_path)
        if not rows:
            raise SystemExit(f"no data found under {cicids_path}")
        return rows, "cicids-2017"
    raise SystemExit(f"unknown dataset: {dataset}")


def _matrix(reqs: Iterable[LabelledRequest]) -> tuple[np.ndarray, np.ndarray]:
    X_rows: list[list[float]] = []
    y: list[int] = []
    for r in reqs:
        feats = featurize({
            "method": r.method, "path": r.path, "query": r.query,
            "body": r.body, "user_agent": r.user_agent,
        })
        X_rows.append([feats[c] for c in FEATURE_COLUMNS])
        y.append(r.label)
    return np.asarray(X_rows, dtype=np.float64), np.asarray(y, dtype=np.int64)


def _train_lr(X_tr: np.ndarray, y_tr: np.ndarray) -> LogisticRegression:
    m = LogisticRegression(max_iter=1000, n_jobs=None)
    m.fit(X_tr, y_tr)
    return m


def _train_xgb(X_tr: np.ndarray, y_tr: np.ndarray) -> XGBClassifier:
    assert HAS_XGB, "xgboost not installed"
    m = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        objective="binary:logistic",
        eval_metric="logloss",
        n_jobs=1,
        verbosity=0,
        random_state=42,
    )
    m.fit(X_tr, y_tr)
    return m


def _train_iforest(X_tr: np.ndarray, y_tr: np.ndarray) -> IsolationForest:
    benign_only = X_tr[y_tr == 0]
    m = IsolationForest(
        n_estimators=150, contamination="auto", random_state=42, n_jobs=1,
    )
    m.fit(benign_only if len(benign_only) > 0 else X_tr)
    return m


def _scores_from_model(model_name: str, model: object, X: np.ndarray) -> np.ndarray:
    if model_name == "iforest":
        # decision_function: positive = inlier, negative = outlier.
        df = model.decision_function(X)  # type: ignore[attr-defined]
        # normalise to [0, 1] anomaly score.
        rng = df.max() - df.min()
        if rng < 1e-9:
            return np.zeros_like(df)
        return 1.0 - (df - df.min()) / rng
    proba = model.predict_proba(X)[:, 1]  # type: ignore[attr-defined]
    return np.asarray(proba)


def _predict_from_scores(scores: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    return (scores >= threshold).astype(np.int64)


def _cv_metrics(
    model_name: str,
    estimator: object,
    X: np.ndarray,
    y: np.ndarray,
    seed: int,
    n_splits: int,
) -> dict[str, dict[str, float]]:
    """Stratified K-fold CV → mean/std for the supervised metrics.

    SAFETY: IsolationForest is unsupervised — sklearn's cross_validate
            with `scoring=` for binary metrics requires .predict(); IF
            does have a .predict() but it returns ±1, not 0/1, so the
            scorer mismatches. We skip it; for IF the single-split
            number stays the only one we publish.
    """
    if model_name == "iforest":
        return {}

    # WHY: cloning ensures every fold gets a fresh, untouched estimator.
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    scoring = ("precision", "recall", "f1", "roc_auc")
    cv_out = cross_validate(
        clone(estimator),  # type: ignore[arg-type]
        X, y, cv=skf, scoring=scoring,
        n_jobs=1, return_train_score=False,
    )

    out: dict[str, dict[str, float]] = {}
    for s in scoring:
        col = cv_out[f"test_{s}"]
        out[s] = {"mean": float(np.mean(col)), "std": float(np.std(col))}
    return out


def train_all(
    dataset: str = "synthetic",
    csic_path: Path | None = None,
    out_dir: Path | None = None,
    seed: int = 42,
    *,
    cicids_path: Path | None = None,
    cv_folds: int = 5,
) -> list[TrainOutput]:
    rows, ds_name = _load(dataset, csic_path, cicids_path, seed)
    X, y = _matrix(rows)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)

    # WHY: outputs go under a versioned subdir; the active version
    #      is chosen by the registry, not by the trainer itself.
    if out_dir is None:
        version = datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%S")
        out_dir = Path("ml/models") / version
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[TrainOutput] = []
    pairs: list[tuple[str, object]] = [
        ("lr", _train_lr(X_tr, y_tr)),
        ("iforest", _train_iforest(X_tr, y_tr)),
    ]
    if HAS_XGB:
        pairs.insert(1, ("xgboost", _train_xgb(X_tr, y_tr)))

    import joblib

    for model_name, model in pairs:
        scores = _scores_from_model(model_name, model, X_te)
        preds = _predict_from_scores(scores, threshold=0.5)
        report = evaluate(
            model_name=model_name, dataset=ds_name,
            y_true=y_te, y_pred=preds, scores=scores,
            n_train=len(X_tr), n_test=len(X_te),
        )
        # WHY: K-fold gives stability bands — the single-split metrics
        #      above are headline numbers; metrics_cv is what we cite
        #      in CP-2 as proof the model isn't seed-fragile.
        if cv_folds and len(X) >= cv_folds * 4:
            report.metrics_cv = _cv_metrics(
                model_name, model, X, y, seed=seed, n_splits=cv_folds,
            )
        artefact = out_dir / f"{model_name}.pkl"
        joblib.dump(model, artefact)
        (out_dir / f"{model_name}.json").write_text(
            json.dumps(report_to_dict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        outputs.append(TrainOutput(model_name, artefact, report))

    # Combined comparison file — flat dict keyed by model name.
    combined = {o.model_name: report_to_dict(o.report) for o in outputs}
    (out_dir / "report.json").write_text(
        json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    return outputs


def _register_outputs(outs: list[TrainOutput], *, activate_algo: str | None) -> None:
    """Push each trained model's metadata into Postgres ml_models.

    WHY: the training step stays standalone, but `make train` is the
         deploy-loop entrypoint, so registering here keeps the workflow
         one command end-to-end. If Postgres isn't reachable the trainer
         still leaves the .pkl files behind for retry.
    """
    from . import registry  # local import: psycopg only loaded when needed

    for o in outs:
        try:
            reg = registry.register(
                version=f"{o.report.dataset}-{o.report.trained_at}-{o.model_name}",
                algo=o.model_name,
                trained_at=o.report.trained_at,
                dataset=o.report.dataset,
                metrics=o.report.metrics,
                artifact_path=o.artifact_path,
                activate=(activate_algo is not None and o.model_name == activate_algo),
            )
            print(f"  registered {o.model_name} as {reg.version} active={reg.is_active}")
        except Exception as e:  # noqa: BLE001 — trainer must keep going
            # NOTE: we deliberately don't fail the run; the .pkl is on disk.
            print(
                f"  WARN: registry insert failed for {o.model_name}: {e}",
                file=sys.stderr,
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="waf-ml-train")
    ap.add_argument("--dataset", choices=["synthetic", "csic", "cicids"], default="synthetic")
    ap.add_argument("--csic-path", type=Path, default=None)
    ap.add_argument("--cicids-path", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--register",
        action="store_true",
        help="Insert ml_models rows into Postgres after training.",
    )
    ap.add_argument(
        "--activate",
        choices=["lr", "xgboost", "iforest"],
        default=None,
        help="Mark this algo's freshly-trained version is_active=TRUE.",
    )
    args = ap.parse_args(argv)

    outs = train_all(
        args.dataset,
        args.csic_path,
        args.out,
        args.seed,
        cicids_path=args.cicids_path,
    )
    for o in outs:
        m = o.report.metrics
        print(
            f"  {o.model_name:8} F1={m['f1']:.3f} AUC={m['roc_auc']:.3f} "
            f"P={m['precision']:.3f} R={m['recall']:.3f}"
        )
    print(f"models written to {outs[0].artifact_path.parent}")

    if args.register or args.activate:
        _register_outputs(outs, activate_algo=args.activate)

    return 0


if __name__ == "__main__":
    sys.exit(main())
