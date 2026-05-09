# ADR-0011 — ML block-mode: threshold, rollback, kill-switch

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

Sprint 9 wired the Lua subrequest in *annotate-only* mode: nginx adds
`X-WAF-ML-Prob` to every request and never blocks. Sprint 10 wants to
flip the block on, but cautiously — a misconfigured ML side could
take down the entire app's protective tier. We need:

1. A calibrated threshold based on real labelled data, not a guess.
2. A way to flip the block off **without rebuilding the proxy image**.
3. Audit-log evidence of every threshold change.

## Decision

### Threshold lives in `ml_config`, not env

Adding a Postgres row `ml_config(key='ml_block_threshold', value='0.93')`
gives us:

- Audit trail (`updated_at`, `updated_by`, history via `audit_log`).
- RBAC (only `admin` can `PUT /ml/threshold`).
- Atomic rollback through the UI slider; no compose redeploy.
- Single source of truth: backend exposes it, ml-service stores its
  calibrated default per model in the registry's `metrics` blob,
  but the *active* threshold is always whatever `ml_config` says.

### Lua reads it through nginx env, refreshes on reload

`ML_BLOCK_THRESHOLD` env (default `1.0`) → nginx
`set $ml_block_threshold "${ML_BLOCK_THRESHOLD}";` → Lua reads
`tonumber(ngx.var.ml_block_threshold) or 1.0`. Changing the threshold
through the UI requires a `nginx -s reload` (Sprint 10) — Sprint 11
adds shared-dict polling so changes take effect within 30 s without
reload.

### Calibration is "lowest θ at FPR ≤ target"

```
θ* = min { θ : FPR(θ) ≤ target_fpr }
```

WHY the *minimum*: at FPR=1% budget we want maximum recall, so we
push θ as low as the FPR constraint allows. A "median" or "balanced"
threshold under-uses the FP budget.

### Rollback contract

Three independent kill-switches, fastest first:

1. **UI slider → 1.0**, takes effect on next nginx reload (~30 s).
2. **`ML_BLOCK_THRESHOLD=1.0` env**, takes effect on next compose up.
3. **`PROXY_FLAVOR_DOCKERFILE=Dockerfile`**, removes Lua subrequest
   entirely; full rebuild but always works.

If any of these is unreachable the operator can hard-restart the
proxy with the upstream image and lose the Lua path completely. ML
annotation in the UI still works (it's served by `/api/v1/ml/inspect`,
not by nginx).

### What we do NOT block on

- **Cache-hit ml-service responses.** Cached `prob` is honoured —
  cache TTL is 30 s, so the worst staleness window is 30 s after a
  threshold change, which is acceptable.
- **`prob == None`** (fallback). Always pass through — we never
  block on missing ML.
- **Static asset paths.** Sprint 11 adds a per-route opt-out
  (`location ~* ^/static/` skips Lua subrequest entirely).

## Consequences

Positive:
- Operator can calibrate, watch, rollback without touching containers.
- Threshold change is auditable via existing audit infrastructure.
- Three independent kill-switches give defence-in-depth.

Negative:
- Sprint 10 reload-on-change is annoying; Sprint 11 fixes with
  shared-dict polling.
- `ml_config` is one new table to migrate; minor.

## Alternatives considered

- **Hard-code threshold per model in joblib.** Rejected — operator
  cannot rollback without retraining.
- **Threshold in env only.** Rejected — no audit trail, no UI.
- **Two thresholds (warn-line + block-line).** Considered for
  Sprint 11; out of scope here.

## Follow-ups

- Sprint 11 — shared-dict polling for threshold (no nginx reload).
- ADR-0013 — per-route opt-out (Lua skip on static assets).
