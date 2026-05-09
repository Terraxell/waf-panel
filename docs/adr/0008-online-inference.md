# ADR-0008 — Online ML inference: SLO, fallbacks, scope

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

 produced offline-trained `lr.pkl`, `xgboost.pkl`,
`iforest.pkl` plus the Postgres `ml_models` registry.  needs
to put those weights on the request path. We want the dashboard to
show probability-of-attack for traffic events alongside ModSecurity
verdicts, and we want a clear path to enabling block-mode in
 We also want the ML side to be impossible to break the
gateway with — no slow ML query may stall a user request.

## Decision

### Separate `ml-service` container, not in-process

The FastAPI gateway already does business logic (auth, rules, audit).
Loading XGBoost into the same process would:

1. Add ~400 MB to the runtime image even when ML is disabled.
2. Couple the gateway's restart cycle to ML deploys: bumping a model
   means bumping the gateway image.
3. Block the event loop on `joblib.load` for tens of milliseconds at
   startup, slowing the gateway's readiness.

A standalone `ml-service` (FastAPI + Uvicorn) keeps these concerns
isolated, lets us scale the ML container independently if needed,
and matches the way every real WAF vendor structures the same split
(deny path = fast and dumb; ML = elastic and fail-open).

### `POST /score` is read-only and returns shape-stable JSON

No DB writes. No registry mutations. The endpoint:

- Looks up the active model (`registry.get_active`) **on startup**,
  not per request, and refreshes only on `SIGHUP` / `/admin/reload`
  (deferred to ).
- Calls `featurize` from the same `waf_ml.features` module the
  trainer used. Drift between train and inference would break model
  quality silently — making this import the contract is the only
  honest way to keep them in sync.
- Returns `{prob, model, model_version, latency_ms, cached}` always
  in the same shape. When no model is active, `prob = null` and
  `fallback_reason = "no_active_model"`.

### Redis as best-effort cache, never a dependency

Cache key: `sha1(method + path + query)`. TTL: 30 s. Two reasons:

1. The same path/query repeats across a session — caching cuts
   latency for the dashboard's polling-style reads.
2. If a bot probes the same URL 1 000 times, we score it once.

Cache miss is normal. Cache **error** is also normal — Redis
unreachable just means we recompute. We never block on Redis.

### Backend proxy with 20 ms p99 budget

The backend mediates between the panel UI and `ml-service`:

- 20 ms timeout end-to-end. Shorter than the 30 s React Query
  refetch interval, longer than the model's own p99 (15 ms).
- 0 retries. A retry on the request path increases tail latency,
  it does not decrease it.
- On timeout / 5xx → return `{prob: null, fallback: true,
  fallback_reason: "timeout"|"error_5xx"|"network"}`. The UI
  renders `—` and a tooltip; ModSecurity verdicts continue to
  drive blocking.

### What this release does NOT do

- **Block on ML.** No `if prob > 0.95: return 403`. Premature.
  We need the FPR distribution from CSIC/CICIDS first, plus an
  override for `is_active=false → never block`. 
- **nginx Lua subrequest.** The current `owasp/modsecurity-crs:nginx-
  alpine` image does not carry `lua-nginx-module`. Switching to
  OpenResty + a custom ModSecurity build is its own migration —
   with `WAF_USE_LUA` feature flag.
- **Per-prediction explanations (SHAP).** `shap` adds 200 MB and
  costs ~5–20 ms per request. Adds: it as an opt-in
  endpoint `/explain` separate from `/score`.

## Consequences

Positive:
- Ship-able online inference path with no gateway risk.
- Dashboard gets a real ML signal for CP-2 demo.
- Clear extension points (Lua, SHAP, block-mode) live behind
  feature flags / future ADRs.

Negative:
- One more container in compose. Documented in the README diagram.
- Operators need to know that `prob` may be null for two reasons:
  no active model, or backend-proxy timeout. We surface both via
  `fallback_reason`.

## Alternatives considered

- **Embed ML in the FastAPI gateway.** Rejected — image bloat,
  startup cost, and the wrong restart-cycle coupling.
- **Use AWS SageMaker / managed inference.** Rejected for this
  course project. The point is to demonstrate the engineering, not
  outsource it.
- **Synchronous block-mode from day one.** Rejected — calibration
  not done, no FPR budget.

## Follow-ups

- ADR-0009  — Lua subrequest path, OpenResty migration.
- ADR-0010  — block-mode threshold and rollback.
