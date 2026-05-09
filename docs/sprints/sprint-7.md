# Sprint 7 — ML offline pipeline (week 8)

- Window: week 8 of the 12-week roadmap
- Driver: produce an offline-trained ML classifier of HTTP requests
  with reproducible metrics, wired into the project's `ml_models`
  registry. Online inference is the next sprint.

## Definition of Done

- [ ] `ml/` package with its own `pyproject.toml`. Stays isolated
      from `backend/` so dependencies don't leak into the FastAPI image.
- [ ] `ml/src/waf_ml/features.py` is the **single source of truth**
      for HTTP-request features. The same function will be imported
      by Sprint 8's online inference path.
- [ ] Loaders for CSIC 2010 and CICIDS 2017 plus a small synthetic
      fixture for tests that don't depend on external downloads.
- [ ] Three models are trained and compared on the same split:
      Logistic Regression baseline, XGBoost, Isolation Forest.
- [ ] `ml/src/waf_ml/eval.py` writes a single JSON report with
      precision, recall, F1, ROC-AUC, FPR-at-recall-0.99 per model.
- [ ] `ml/src/waf_ml/registry.py` serialises the trained model as
      pickle plus JSON metadata, and writes a row into `ml_models`
      via direct psycopg connection (separate from the FastAPI ORM
      to keep the trainer standalone).
- [ ] `make train` (and `dev.ps1 train`) wraps the whole pipeline:
      load → feature → split → train → eval → register.
- [ ] Tests:
      - `test_features.py` — golden-file feature stability.
      - `test_train.py` — smoke run on synthetic data, all three
        models train and report metrics within sane bounds.
      - `test_eval.py` — eval-report shape correctness.

## Out of scope

- Online inference path (nginx → /ml/score) — Sprint 8.
- SHAP-based feature importance UI — Sprint 9.
- Drift detection (PSI, KS) — Sprint 9.
- Real CSIC / CICIDS dataset fetch in CI — heavy and licence-aware;
  the loader supports a local path passed in via env, defaulting to
  `ml/datasets/raw/`.

## Notes

### Why a separate `ml/` package, not inside `backend/`

Two reasons:

1. **Image size.** scikit-learn + xgboost + their numpy/scipy
   compile-time deps add ~400 MB to the runtime image. The FastAPI
   gateway has no business carrying them. Sprint 8's online ML
   service ships in its own image.
2. **Reproducibility.** The trainer wants `pandas`, `joblib`,
   `matplotlib` for plots. Adding them to FastAPI's `pyproject.toml`
   pollutes the dev experience for someone who only edits the API.

### Why share `features.py` between training and inference

If the function that turns a request into a feature vector lives in
two copies, training and inference will silently drift the moment
either copy gets touched. We import the same module from both places
and lock the contract with a `tests/test_features.py` golden-file
comparison.

### Model choices

- **Logistic Regression** — baseline. Anything below this isn't worth
  shipping. Linear with L2 penalty, no fancy tricks.
- **XGBoost** — main classifier. Tabular, sparse features, gradient
  boosting with early stopping.
- **Isolation Forest** — unsupervised companion. Trained only on
  benign traffic, useful when labels are unavailable. Sprint 9 will
  combine it with XGBoost as a per-request anomaly score in the
  hybrid decision logic.

### Feature engineering (HTTP-request → vector)

Two layers, no deep learning:

| Family       | Examples                                                      |
|--------------|---------------------------------------------------------------|
| **Lengths**  | `len_url`, `len_query`, `len_body`, `n_params`                |
| **Special**  | counts of `' " < > ; / * = % & |` and `--`, `n_special`       |
| **Entropy**  | Shannon entropy of path and query                             |
| **Tokens**   | counts of SQL/XSS/RCE indicators (`UNION`, `SELECT`, `<script`, `eval(`, `../../`, `/etc/passwd`) |
| **Encoding** | ratios of url-encoded and base64-ish substrings               |
| **Headers**  | UA class (`bot`/`browser`/`unknown`), method, has_referer     |

These are the same features `traffic_features` table will store once
Sprint 8 wires the online side.

## Carry-over to Sprint 8

- Online inference: `ml-service` container, FastAPI + `joblib.load`
  on startup, `POST /score` returning probability + top-3 SHAP
  contributions.
- nginx Lua subrequest into `/score` with cache (Redis) and a per-
  request budget (5 ms p95, 20 ms p99 fallback).
- AWS WAF adapter (boto3) — optional, behind a feature flag.
