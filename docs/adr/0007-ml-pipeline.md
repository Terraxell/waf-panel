# ADR-0007 — ML pipeline shape: features, models, registry

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

The project's value-add over a plain CRS deployment is the ML detector
that catches what signatures miss. To make that claim defensible we
need three things:

1. A **stable feature contract** between training and online inference.
2. A **comparable evaluation** of multiple models on the same split,
   so the choice of XGBoost over a baseline is empirical, not
   aesthetic.
3. A **registry** so the API knows which model is currently active
   and can swap it without code changes.

## Decision

### Feature engineering — `ml/src/waf_ml/features.py`

One pure function `featurize(req: dict) -> dict[str, float]`. It takes
a normalised request dict (method, path, query, body, headers) and
returns a flat numeric dict. No I/O. No global state. The same module
is imported by:

- `ml.train.run` to produce training and validation matrices.
- The the online inference service to vectorise live requests.
- `tests/test_features.py` golden-file test that pins the exact
  output for a fixed input.

Feature families are listed in the project plan (lengths, specials,
entropy, tokens, encoding ratios, headers).

### Models

Three models, trained on the same train/val split:

- **Logistic Regression** with L2 penalty — baseline. Sub-second
  training, easy to inspect coefficients on defence.
- **XGBoost** with `binary:logistic` objective, early stopping on
  validation log-loss. Picked as the production candidate based on
  the evaluation.
- **Isolation Forest** trained on benign-only — provides an unsupervised
  anomaly score that the hybrid pipeline  blends with the
  XGBoost score using `max(score_xgb, score_iforest_normalised)`.

### Evaluation

`ml/src/waf_ml/eval.py` writes one `report.json` per training run.
Schema:

```json
{
  "model": "xgboost",
  "trained_at": "2026-05-08T15:20:00Z",
  "dataset": "synthetic-v1",
  "n_train": 8000,
  "n_test": 2000,
  "metrics": {
    "precision": 0.96,
    "recall": 0.92,
    "f1": 0.94,
    "roc_auc": 0.99,
    "fpr_at_recall_0_99": 0.04
  },
  "confusion_matrix": {"tn": ..., "fp": ..., "fn": ..., "tp": ...},
  "thresholds": {"recall_0_90": 0.45, "recall_0_99": 0.32}
}
```

The schema is the same across all three models — a downstream
comparator can pick the best by F1.

### Registry

`registry.py` writes:

- `ml/models/<version>/model.pkl` — joblib artefact.
- `ml/models/<version>/report.json` — eval report.
- One row in PostgreSQL `ml_models`: `(version, algo, trained_at,
  dataset, metrics, artifact_path, is_active)`. Only one active at
  a time (partial unique index already in place).

Activation is a separate explicit step (`waf-ml activate <version>`),
not auto-on-train. The course-project equivalent of "promote to
prod".

## Alternatives considered

- **One model class only (XGBoost).** Rejected: defence wants the
  baseline-vs-main comparison, and the Isolation Forest covers the
  unlabeled regime that XGBoost can't.
- **Online retraining on every request.** Rejected for any project
  this size: noisy, hard to roll back, would need a feature store.
- **Embedding-based classifier (DistilBERT on URL tokens).** Rejected:
  overkill, hard to reproduce, doesn't outperform XGBoost on tabular
  HTTP features at our scale.

## Follow-ups

- ADR-0008  — online inference SLO, error budget, fallbacks.
- ADR-0009  — drift detection rules and operator UX.

## Addendum (post-release close-out)

After the initial initial wrap we tightened three places to satisfy
the DoD without caveats:

- **CICIDS 2017 loader.** The DoD listed both CSIC 2010 *and*
  CICIDS 2017; only CSIC shipped. We added a flow-CSV loader that
  projects rows onto the same `LabelledRequest` schema, so the
  trainer can mix datasets. CICIDS labels are heterogeneous
  (`SSH-Patator`, `Web Attack – XSS`, etc.); we collapse anything
  ≠ `BENIGN` to `label=1` and leave per-class breakdown for
  
- **Stratified K-fold metrics.** A single 80/20 split gave one
  number per metric — fine for development, weak for CP-2. Added
  `EvalReport.metrics_cv` with mean/std over 5 stratified folds
  (LR, XGBoost). IsolationForest is unsupervised so it skips CV
  and stays with single-split numbers.
- **Registry under test.** `registry.py` was untested. We stub the
  `psycopg` module via `sys.modules` and assert the full SQL
  sequence: deactivate-all → upsert → activate-this-id, plus the
  POSIX-normalisation of artifact paths and JSON-serialisation of
  metrics. No live Postgres needed, contract is locked.
