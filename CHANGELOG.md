# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

— (Sprint 15+: real CSIC bench, mTLS between containers, multi-region
IPSet sync, signed model artefacts, full ClickHouse migration runner)

## [1.1.1] — 2026-05-19

Sprint 14 — bootstrap completeness hotfix. Closes four production-
readiness gaps found via end-to-end smoke against a clean docker-compose
stack. Pure infrastructure / data-migration fixes; no API contract
changes, no behavioural regressions.

### Added

- `alembic 0003`: idempotent seed of default admin
  (`admin@example.com` / `admin`, never overwrites a rotated password).
- `make ch-migrate` / `.\dev.ps1 ch-migrate`: re-apply
  `infra/clickhouse/init.sql` against a running ClickHouse — solves
  "old volume + new schema" gap.
- `make bootstrap` / `.\dev.ps1 bootstrap`: one-shot helper that runs
  alembic + ch-migrate in order. Idempotent.
- `docs/sprints/sprint-14-{plan,summary}.md`.

### Changed

- Vector pipeline (`infra/vector/vector.toml`): `modsec_decode` now
  probes `transaction.client_ip` → `transaction.remote_address` →
  top-level `client_ip` for the source IP. Fixes empty `remote_ip` on
  modsec-blocked rows in ClickHouse.
- README "Boot the stack" section rewritten — `make bootstrap` is
  now the documented first-run command.

### Fixed

- `traffic_log.remote_ip` no longer empty for ModSec events,
  unblocking `uniqExact(remote_ip)` in `metrics/overview` and the
  AWS WAF adapter's RFC1918/loopback filter.
- Default-admin login flow (`admin@example.com` / `admin`) now works
  immediately after `make bootstrap` instead of returning 401.
- `bench/tests/test_run.py` truncation: trailing null bytes that crept
  in during a previous Edit-tool flush — file rewritten clean.

## [1.1.0] — 2026-05-12

Sprint 13 — post-defence audit C-list. Pure additions and opt-in
features; no breaking changes vs `v1.0.0`. The default request path,
default UI render, and default ML-service behaviour are unchanged.

### Added

- Security-headers middleware (CSP, HSTS, X-Frame-Options DENY,
  X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy).
- Bulk rule import: `POST /api/v1/rules/bulk` with `dry_run` default
  and per-row error reporting; admin-only.
- Drift-report viewer API: `GET /api/v1/drift` (list, newest-first)
  and `GET /api/v1/drift/{name}` (full report); path traversal hard
  rejected.
- Notification webhook adapter (Slack-compatible) with per-channel
  cooldown and fail-soft semantics.
- Optional TreeSHAP-backed `/explain` path (`ML_USE_SHAP=true`); falls
  back to the legacy weights × feature path for non-tree models or if
  `shap` is missing.
- Frontend: dark mode (light / auto / dark), Popover replacing native
  `title=` on `MlBadge` (keyboard-accessible, instant, structured),
  mobile-responsive CSS at 920 / 720 px breakpoints, reduced-motion
  honored globally.
- vitest coverage: `MlBadge`, `MlThresholdSlider`, `Popover`,
  `ThemeProvider` (23 new specs).
- 4 locale strings × 4 languages for the theme switcher.

### Changed

- OpenResty Lua subrequest now skipped on `^/static/`,
  `/favicon.ico`, `/robots.txt`, `/__health`, `/healthz`, `/readyz`
  (per-route opt-out; ADR-0010 addendum).
- `ExplainMethod` enum extended with `"shap"`.

### Security

- CSP `frame-ancestors 'none'` is the new baseline.
- HSTS emitted only on https connections (preserves dev-http boot).
- Bulk-import enforces a 500-row hard cap before reaching the DB.

## [1.0.0] — 2026-05-15

First taggable release. Closes the 12-week course-project roadmap with
all three checkpoints (CP-1, CP-2, CP-3) and the post-defence audit
hotfixes from Sprint 11. The stack boots end-to-end on Docker Desktop
(Windows / Linux / macOS), 170+ unit tests pass without infrastructure,
and the .docx plan carries an addendum with real numbers.

### Added — protective layer (Sprints 1–2)

- nginx + ModSecurity v3 + OWASP CRS v4 (1700 rules, paranoia 1)
  blocking SQLi / XSS / RCE on the request critical path.
- DVWA target behind the proxy for stand testing.
- Vector 0.40 log shipper: nginx access JSON + ModSec audit JSON →
  ClickHouse `traffic_log`.
- `docs/troubleshooting.md` — 18 documented edge cases hit during
  first-bring-up.

### Added — backend gateway (Sprint 3)

- FastAPI + SQLAlchemy 2 (async) + Alembic gateway with RBAC
  (`admin / analyst / viewer`).
- `users / rules / incidents / audit_log / ml_models` schema in Postgres
  (`infra/postgres/init.sql` + Alembic 0001 idempotent migration).
- argon2id password hashing, JWT HS256 access tokens with email claim.
- Repository protocol + InMemory + Pg implementations for testability.
- Service layer: `auth_service`, `rules_service` with audit logging.

### Added — dashboard SPA (Sprints 4–6)

- React 18 + TypeScript + Vite + React Router + React Query SPA.
- Hand-authored CSS design system (4 colors, monospace + serif typography,
  `--radius: 0`).
- Pages: Login, Dashboard (RPS / blocked / unique IPs / rules / ML
  status, Recharts AreaChart), Incidents, Rules editor, Audit.
- `MlBadge` chip + tooltip with top-3 contributors on Incidents.
- ClickHouse async client (`httpx` + JSONEachRow) with materialized-view
  reads (`rps_per_minute`, `top_attacks_lifetime`).
- ADR-0001 through ADR-0006.

### Added — offline ML pipeline (Sprint 7)

- `ml/` package: `waf_ml.features` (25-feature `featurize` — single
  source of truth for trainer + inference), `train`, `eval`, `registry`,
  CSIC 2010 + CICIDS 2017 + synthetic dataset loaders.
- `train_all`: LR + XGBoost + IsolationForest on the same stratified
  split, stratified 5-fold CV (mean ± std).
- `EvalReport` shape: precision / recall / F1 / ROC-AUC /
  FPR-at-recall-0.99, confusion matrix, thresholds.
- `registry.register / get_active` with Postgres `ml_models` upsert
  (partial unique index for `is_active`).
- `make train` + `make train-register` + `make ml-promote` targets.

### Added — online inference (Sprint 8)

- `ml-service` container (FastAPI + joblib): `POST /score`, `/healthz`,
  `/readyz`. Loads active model from registry → filesystem fallback.
- Redis-backed score cache with 30 s TTL, fail-open on Redis errors.
- Backend proxy `POST /api/v1/ml/inspect` with 20 ms p99 timeout and
  fail-open response shape (`prob: null`, `fallback: true`,
  `fallback_reason`).
- ADR-0007, ADR-0008.

### Added — explanations and drift (Sprint 9)

- `POST /explain` in ml-service: top-K feature contributors via
  `model.coef_` (LR) or `feature_importances_` (XGBoost), normalised
  to absolute-sum = 1.0.
- Backend proxy `POST /api/v1/ml/explain` with the same fail-open envelope.
- `waf_ml.drift` module: PSI (10 equal-frequency bins) + Kolmogorov–
  Smirnov via `scipy.stats.ks_2samp`. CLI:
  `python -m waf_ml.drift --baseline X.csv --current Y.csv`.
- OpenResty + Lua-subrequest proxy flavour
  (`PROXY_FLAVOR_DOCKERFILE=Dockerfile.openresty`) — opt-in,
  annotate-only at this stage.
- ADR-0009, ADR-0010.

### Added — block-mode and attack bench (Sprint 10, CP-3)

- `waf_ml.threshold` calibration: `θ* = min{θ : FPR(θ) ≤ target_fpr}`
  with full ROC-trace JSON.
- Block-mode wired into `infra/nginx/lua/score.lua`: configurable via
  `ML_BLOCK_THRESHOLD` env / UI slider; three independent kill-switches
  (UI, env, proxy flavour fallback). Default 1.0 (annotate-only).
- `bench/` package: 100 benign + 100 labelled attack probes (SQLi /
  XSS / path traversal / RCE / SSRF / Log4Shell / tooling fingerprints),
  async `bench.run` driver, FPR / FNR / p50 / p95 / p99 latency
  reporting, exit code 0 ≤ 5% FPR / 30% FNR else 2.
- AWS WAFv2 IPSet adapter: opt-in via `WAF_AWS_ENABLED=true`, fail-soft
  on AWS errors, 5-minute rate-limit floor, RFC1918 / loopback filter.
- Backend `GET / PUT /api/v1/ml/threshold` (admin-only PUT, audit row).
- Frontend `MlThresholdSlider` with rollback button on the Rules page.
- ADR-0011, ADR-0012.

### Added — persistence, drift worker, plan addendum (Sprint 11)

- Postgres `ml_config(key, value_text, updated_at, updated_by)` table
  + Alembic 0002 + `MlConfigRepo` Protocol + InMemory / Pg
  implementations. Threshold endpoint now reads / writes this table.
- `backend/workers/drift_worker.py`: pulls last-N-hours raw HTTP rows
  from `traffic_log`, runs the same 25-feature `featurize`, compares
  against frozen baseline, writes audit row
  (`ml.drift.{clean|warn|alert|skipped}`). `make drift-check` target.
- `scripts/build_plan_addendum.py`: appends Приложение Б to
  `План_курсового_проекта_WAF.docx` with real numbers (≈156 tests
  count by package, 12 ADRs, CP-2 / CP-3 actuals).

### Added — i18n (Sprint 12)

- Lightweight in-process i18n (`frontend/src/lib/i18n.tsx` + `locales/`)
  for **RU / EN / DE / FR**. Type-checked dictionaries; missing key on
  any side is a build-time error.
- Browser auto-detect via `navigator.language`, persisted in
  `localStorage`. Updates `<html lang>` for accessibility / SEO.
- `LanguageSwitcher` segmented toggle in the shell header.
- All four pages, two ML widgets, login, layout — translated.
  `localeTag` map drives `Date.toLocaleString` per language.

### Security — Sprint 11 hotfix

- `POST /auth/login` rate limit: 5 attempts per `(ip, lower(email))`
  per 60 s, sliding-window in-process backend, fail-open on internal
  error. Returns 429.
- Production startup guard refuses to start with a default
  `JWT_SECRET` or any secret < 32 chars when `WAF_ENV=production`.
- Drift worker now compares all 25 features (was 6 numerical columns
  before) — token-flag drift (UNION/SELECT, `<script`, `/etc/passwd`,
  …) is now part of the alert surface.
- IsolationForest `decision_function` normalisation switched to
  stable sigmoid; previous per-batch min/max collapsed to 0 on
  single-row online inference.

### Fixed

- Sprint 4 hotfix: email claim added to JWT (was showing
  `unknown@example.com` on the dashboard); CSS overflow on long emails
  in dashboard cards.
- Multiple Windows + Docker Desktop bring-up issues across sprints,
  documented in `docs/troubleshooting.md`.

### Tooling

- Make + `dev.ps1` parity (Linux / macOS + Windows).
- `.github/workflows/ci.yml`: 6 jobs (backend, ml, ml-service, bench,
  frontend, ci-ok aggregator) with concurrency cancel-in-progress.
- ruff configured uniformly across all four Python packages
  (line-length 100, py3.11 target).

### Test totals at v1.0.0

| Package      | Tests | What runs                                          |
|--------------|-------|----------------------------------------------------|
| backend      | 81    | auth/RBAC, rules, incidents, audit, ml inspect/explain/threshold, aws_waf, drift_worker, login rate-limit, JWT guard |
| ml           | 55    | features, datasets, train, eval, registry, cicids, drift, threshold |
| ml-service   | 22    | score, explain, healthz, cache fail-open, model loader, IF batch=1 |
| bench        | 5     | FPR/FNR arithmetic on stub server, JSON report     |
| **total**    | **163** | full suite runs in ~7 s without Postgres/CH/Redis |

## Tag instructions

After CI is green on `main`:

```bash
git tag -a v1.0.0 -m "v1.0.0 — course-project release, CP-1/2/3 closed"
git push origin v1.0.0
```

Then create a GitHub Release, paste the [1.0.0] section above as the body.
>`, etc.).

## Tagging

After CI is green on `main`:

```bash
git tag -a v1.1.0 -m "v1.1.0 — Sprint 13: post-defence audit C-list"
git push origin v1.1.0
```
