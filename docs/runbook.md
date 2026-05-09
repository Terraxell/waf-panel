# Operational runbook

Day-2 procedures for `waf-panel`. Each section is self-contained:
**Symptom → Diagnose → Mitigate → Verify → Postmortem hook**.

This is what an operator opens at 3 AM, not the README. Keep entries
short and reproducible.

## Conventions

- Commands assume the project root is `cwd`.
- `make X` works on Linux/macOS; the same target lives in `dev.ps1` for
  Windows (`.\dev.ps1 X`). Only the macOS form is shown below.
- `panel` refers to the FastAPI gateway service named `backend` in
  compose. The user-facing SPA is `frontend`.

---

## 1. Stack will not boot — generic

**Symptom.** `docker compose up -d` returns, but `make ps` shows one
or more services restarting / unhealthy.

**Diagnose.** `make logs` and read the last 200 lines per service.
The commonest causes are documented in `docs/troubleshooting.md` (18
entries). For everything else:

```bash
docker compose ps          # which container is RestartLoop?
docker compose logs <svc>  # tail its stderr
```

**Mitigate.**

- If it's a fresh volume corruption: `make nuke` (drops Postgres /
  ClickHouse data) → `make up` → `make migrate`.
- If it's a config drift: `git diff -- .env infra/` and revert the
  unintended change.

**Verify.** `make smoke` — runs end-to-end curl probes. Must exit 0.

---

## 2. ml-service won't start / `/healthz` returns 503

**Symptom.** Backend `/api/v1/ml/inspect` returns
`{"prob": null, "fallback_reason": "network"}`. The dashboard shows
`—` everywhere ML.

**Diagnose.**

```bash
docker compose logs ml-service
curl http://localhost:8001/healthz   # if exposed locally
```

Three usual causes:

1. **No model on disk** — `model_loaded: false`, `status: "degraded"`.
   The container started but the bind-mount `./ml/models/active/` is
   empty.
2. **xgboost / numpy import error** — usually a stale image after `pip`
   bumped a wheel.
3. **Redis unreachable** — service still works (cache fail-open), but
   `/healthz.redis_ok` is false.

**Mitigate.**

```bash
# 1) Train + promote a fresh model.
make train          # writes ml/models/v<TS>/
make ml-promote     # copies the latest version → ml/models/active/
docker compose restart ml-service

# 2) Stale image:
docker compose build --no-cache ml-service
docker compose up -d ml-service

# 3) Redis: see §5 below — ml-service stays up regardless.
```

**Verify.** Reload the dashboard; the `—` chips should turn into
numeric scores within 30 s (cache TTL).

**Postmortem hook.** If this happened in production, write the cause
into ``CHANGELOG.md`` and consider a
`make smoke-ml` target that pings `/healthz` separately.

---

## 3. Drift alert just fired (`audit_log.action='ml.drift.alert'`)

**Symptom.** Audit page shows a row tagged `ml.drift.alert` with a
list of features that breached PSI ≥ 0.25 or KS p < 0.05.

**Diagnose.**

```bash
make drift-check   # re-run the worker; inspect the JSON report
ls ml/drift_reports/      # newest file is the run
```

Open the JSON; the `features` array is sorted by level. Look at:

- `tok_*` features alerting → real attack-distribution shift; the
  baseline likely doesn't match current attacker tooling.
- length/entropy features alerting → traffic-mix shift (new endpoint
  pushing path/query distributions); not necessarily an attack.

**Mitigate.**

- If attack-shift: do **not** retrain blindly on the new data — that
  bakes attacks into the baseline. Investigate, blocklist sources via
  AWS adapter (if enabled), then refresh baseline only on benign
  windows.
- If traffic-mix shift: `make train` against a fresh CSIC/CICIDS pull
  + `make ml-promote`. Refresh baseline:
  `cp ml/models/active/baseline_features.csv{,.bak.<date>}` and
  regenerate from a recent benign window.

**Verify.** `make drift-check` should now return `clean` or `warn`.

**Postmortem hook.** future release adds a scheduled drift worker; until
then this is a manual cron / on-call duty.

---

## 4. Roll back the active ML model

**Symptom.** A newly promoted model misbehaves (block-mode FPR
spikes, dashboard `prob` looks wrong).

**Diagnose.**

```sql
SELECT version, algo, trained_at, is_active
  FROM ml_models
  ORDER BY trained_at DESC LIMIT 5;
```

**Mitigate.** Three increasingly invasive switches (ADR-0011):

1. **Disable block-mode immediately.** UI → Rules page →
   *Roll back (θ = 1.0)* button. Effective on next nginx reload.
2. **Pin to a previous artefact.**

   ```bash
   ls ml/models/v*    # pick a known-good version
   rm -rf ml/models/active
   cp -r ml/models/v<good> ml/models/active
   docker compose restart ml-service
   ```

3. **Drop ML entirely** for the request path:

   ```bash
   echo "PROXY_FLAVOR_DOCKERFILE=Dockerfile" >> .env  # default flavour
   docker compose up -d --build proxy
   ```

   Removes the Lua subrequest. ModSec keeps blocking on rules alone.

**Verify.** `make smoke` + open the dashboard; ML chips should reflect
the rolled-back model's `model_version`.

---

## 5. Redis flaps / unavailable

**Symptom.** `/healthz.redis_ok=false` on ml-service; backend logs
`redis is having a moment` warnings.

**Diagnose.**

```bash
docker compose logs redis
docker compose exec redis redis-cli ping   # expect PONG
```

**Mitigate.** ml-service cache is fail-open — every score recomputes,
no functional impact. If Redis is flapping in a production system,
restart it:

```bash
docker compose restart redis
```

If it loops, drop the data (we treat Redis as cache, not source of
truth) — `make nuke` is a sledgehammer; do this instead:

```bash
docker compose stop redis
docker volume rm waf-panel_redis_data
docker compose up -d redis
```

**Verify.** `redis-cli ping` returns PONG; `/healthz` flips
`redis_ok=true` within a request cycle.

---

## 6. Login locked out (HTTP 429 every attempt)

**Symptom.** `make smoke` or panel login returns 429
`too many login attempts, try again in a minute`.

**Diagnose.** Sliding-window counter is keyed on
`(remote_ip, lower(email))`. Five wrong attempts in 60 s trip it.

**Mitigate.**

- Operator option A: wait 60 s. The bucket drains on its own.
- Operator option B: bounce the backend container — the in-process
  counter is wiped on restart (known limitation; future release moves
  the counter to Redis):

  ```bash
  docker compose restart backend
  ```

**Verify.** `curl -X POST .../auth/login` returns 200 / 401 again.

---

## 7. JWT secret rotation

**Symptom.** Suspected compromise of `JWT_SECRET`, or a routine
quarterly rotation.

**Diagnose.** Audit log will show one suspicious `auth.login.success`
from an unexpected IP / time. Cross-check against `traffic_log` for
the corresponding source.

**Mitigate.**

```bash
# 1) Generate a new secret.
NEW=$(openssl rand -hex 32)

# 2) Update .env (production deploys: your secret-manager).
sed -i.bak "s/^JWT_SECRET=.*/JWT_SECRET=$NEW/" .env

# 3) Roll the backend pod / container.
docker compose up -d --force-recreate backend
```

All existing sessions invalidate immediately. Users re-auth.

**Verify.** Production startup guard refuses to start if the new
value is < 32 chars or in the default-blocklist (see
`backend/src/waf_panel/main.py::_validate_settings`).

---

## 8. Admin password rotation

**Symptom.** Backend refuses to start under `WAF_ENV=production`
with this in the log:

```
RuntimeError: WAF_ENV=production but the seeded admin user
(admin@example.com) still has the default password 'admin'.
```

**Cause.** Alembic migration `0003` seeds `admin@example.com` with
the literal password `admin` so a fresh dev / course-defence stack
boots usable. In production that hash is a known-published default
from this repo, so the startup guard refuses to expose the panel
until it's rotated.

**Mitigate (preferred — uses the project CLI).**

```bash
# Linux / macOS
make rotate-admin EMAIL=admin@example.com
# Windows / PowerShell
.\dev.ps1 rotate-admin -Email admin@example.com
```

The CLI prompts for the new password (no echo, no shell-history
leak), hashes through the same `passlib.argon2` the auth path uses,
and updates the row in one round trip. Restart the backend so the
startup guard re-checks:

```bash
docker compose up -d --force-recreate backend
```

**Mitigate (fallback — pure psql, kept for documentation).**

```bash
# 1) Generate a new password and its argon2id hash. Use the same
#    parameters as passlib's default so verification stays cheap.
python - <<'PY'
import getpass
from passlib.hash import argon2
print(argon2.hash(getpass.getpass("New admin password: ")))
PY

# 2) Patch the row in Postgres. -- replace <HASH> with the output above.
docker compose exec postgres psql -U waf -d waf_panel -c \
  "UPDATE users SET password_hash = '<HASH>' WHERE email = 'admin@example.com';"

# 3) Restart the backend so the lifespan re-checks.
docker compose up -d --force-recreate backend
```

**Verify.** The startup log no longer contains the RuntimeError, and
`POST /api/v1/auth/login` with the *old* password returns 401 while
the new password returns 200.

**Why not bake a CLI for this.** A bootstrap CLI is on the roadmap
(see ADR-0013 follow-ups) but the SQL path is two commands and
zero new code surface — fine for the scope this project ships at.

---

## 9. ClickHouse fills up (`waf_logs` volume > 80%)

**Symptom.** Disk pressure on the host; `clickhouse-client` warnings;
slow dashboard reads.

**Diagnose.** Default TTL on `traffic_log` is 30 days
(`infra/clickhouse/init.sql`). Materialized views inherit history.

```sql
SELECT formatReadableSize(sum(bytes_on_disk)) FROM system.parts
  WHERE database='waf_logs';
```

**Mitigate.** Drop old partitions manually:

```sql
ALTER TABLE waf_logs.traffic_log DROP PARTITION '20260301';
```

Or shorten TTL: edit init.sql + run a migration to apply on the
existing table.

**Verify.** `df -h` on the host; ClickHouse `OPTIMIZE TABLE` to
materialize the deletion.

---

## 10. Backup / restore (planned procedure, not yet automated)

**WHY this is in the runbook.**  backlog has `make backup` /
`make restore`; until then, the steps below are the manual procedure
the operator runs.

**Backup.**

```bash
# Postgres — schema + data.
docker compose exec postgres pg_dump -U waf -d waf_panel \
  > backups/pg-$(date +%Y%m%dT%H%M%SZ).sql

# ClickHouse — per-table.
docker compose exec clickhouse clickhouse-client \
  --user waf --password waf_dev_only -d waf_logs \
  --query "BACKUP TABLE traffic_log TO Disk('backups','traffic_log')"
```

**Restore.** Inverse, with `pg_restore` and `RESTORE TABLE`. **Stop
the backend before restoring** so half-written rows don't appear.

---

## 11. Common defence-time questions

These come up at the course-project review; pre-cached answers:

- **Why fail-open and not fail-closed?** ML is best-effort; ModSec is
  the synchronous block layer. Failing closed on ML would deny all
  traffic when ml-service blips — worse than the attack we're
  preventing.
- **Why annotate-only by default?** Block-mode requires a calibrated
  threshold against real labelled data. Default `θ=1.0` ensures a
  fresh deploy never mass-blocks before calibration.
- **Why one author?** Course project. Production deployment would
  enforce 2-eye PR review through branch-protection on the `ci-ok`
  workflow check.

---

Last updated: v1.0.0 release. See `CHANGELOG.md` for what changed and
`docs/` for per-release context.
