# Threat model — waf-panel v1.0.0

This document is a STRIDE-style threat model for the panel itself.
The protective layer (ModSecurity + CRS) and the protected target
(DVWA in the demo stack) are out of scope; we model attacks against
**the management plane** that operates them.

The model is read top-down: assets → trust boundaries → STRIDE per
boundary → mitigations → residual risk. It is intentionally short
enough to fit into a defense slide if asked.

## 1. Assets

| Asset                                  | Why it matters                                                |
|----------------------------------------|---------------------------------------------------------------|
| Admin / analyst credentials            | Full access to the panel; argon2id-hashed in `users` table.   |
| JWT signing secret                     | Forging valid tokens bypasses every endpoint's RBAC.          |
| `ml_models` table + active flag        | Wrong model in production breaks accuracy or causes outage.   |
| `ml_config.ml_block_threshold`         | Setting θ=0 blocks all traffic; setting θ=1 disables ML defence. |
| `audit_log`                            | Forensic record. Tampering hides operator actions.            |
| ModSecurity audit log volume           | Contains raw HTTP request headers / bodies — PII risk.        |
| AWS WAFv2 IPSet (when enabled)         | Wrong IPs in a public blocklist can self-DoS production.      |
| ClickHouse `traffic_log`               | Raw HTTP traffic; same PII concern as ModSec audit volume.    |

## 2. Trust boundaries

```
            ┌──────────────── public internet ────────────────┐
            │                                                 │
[attacker / browser]──HTTPS──▶[nginx + ModSec]──HTTP──▶[DVWA]
                                       │
                                       ▼
                                  [Vector]
                                       │
            ┌─────── docker-compose private network ────────┐
            │                                               │
            │  [backend FastAPI]──pg──▶[Postgres]           │
            │         │                                     │
            │         ├──http──▶[ml-service]──▶[Redis]      │
            │         └──http──▶[ClickHouse]                │
            │                                               │
            └───────────────────────────────────────────────┘
```

Three boundaries:

1. **Internet ↔ proxy.** Anyone can reach the gateway; ModSec is the
   first line. Authenticated panel users come over the same edge.
2. **Proxy ↔ backend network.** Inside the compose network. Plain
   HTTP between containers; trust assumed within the bridge.
3. **Panel ↔ AWS.** Egress only; rate-limited; opt-in.

## 3. STRIDE

### S — Spoofing

| Threat                                       | Mitigation                                                                                  | Residual                                                              |
|----------------------------------------------|---------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| Stolen JWT used as another admin             | argon2id passwords; 60-min TTL; `email` claim; rotate `JWT_SECRET` per env                  | Compromised secret = full panel takeover until rotated (kill-switch via `WAF_ENV=production` startup guard prevents default secrets shipping to prod) |
| Brute-forced admin login                     | Sliding-window 5/60s per `(IP, email.lower())` → HTTP 429; argon2id is also slow on purpose | Distributed login attempts across IPs would dilute the bucket; Sprint-13 candidate: Redis-backed shared limit |
| Default admin (`admin@example.com / admin`)  | Documented in README + init.sql comment; production startup checks JWT_SECRET, but not the seed user | Operator-discipline gap; Sprint-13 candidate: refuse-to-start when default admin row + production env both true |
| ml-service request-spoofing inside compose   | Plain HTTP inside compose private net; backend trusts the response                          | An attacker on the host network could MITM ml-service. Mitigation candidate (Sprint 13): container-to-container mTLS |

### T — Tampering

| Threat                                                | Mitigation                                                                  | Residual                                  |
|-------------------------------------------------------|-----------------------------------------------------------------------------|-------------------------------------------|
| Panel user edits `ml_block_threshold` to disable ML   | RBAC `admin`-only for PUT, audit row, three independent kill-switches       | Audit ≠ prevention; reviewer approves the change reactively |
| Tamper with `ml_models.is_active`                     | Partial unique index ensures only one active row; UPDATE/INSERT through registry, not raw SQL | Direct DB access bypasses; mitigated by network isolation only |
| Audit-log row mutation / deletion                     | `audit_log` has no UPDATE / DELETE in the API; append-only contract        | Direct DB access can still tamper; out of scope for app-layer mitigations |
| Joblib pickle tampering on disk                       | `ml/models/active/` mounted read-only into ml-service                       | Operator with host write access can swap a malicious .pkl; runtime joblib-load executes arbitrary code on import |

### R — Repudiation

| Threat                                  | Mitigation                                                                              | Residual                                |
|-----------------------------------------|-----------------------------------------------------------------------------------------|-----------------------------------------|
| Operator denies they changed θ          | `audit_log` row with `actor_id` for every PUT /threshold; service-layer audit on rule mutations | Audit log can be silenced upstream of the API by a DB-admin; same as Tampering above |
| Operator denies a rule was created      | `created_by` column on `rules` row + audit trail                                        | Same DB-admin caveat                    |

### I — Information disclosure

| Threat                                            | Mitigation                                                                          | Residual                                          |
|---------------------------------------------------|-------------------------------------------------------------------------------------|---------------------------------------------------|
| Login enumeration (different message for unknown email vs wrong password) | Single error string from `AuthService.login` ("invalid credentials"); same status 401 in both cases | Timing side-channel from argon2id verify only on email-found path; mitigated by `argon2id` constant-cost on a dummy hash when email missing — *Sprint-13 candidate*, currently the email-not-found path returns faster |
| Response leaks of `JWT_SECRET` / Postgres DSN     | Settings never serialised by any endpoint; `Settings.postgres_dsn` is property-only  | Operator-on-host can `cat .env`                   |
| ModSec audit log PII                              | Volume mounted into Vector and ClickHouse; not exposed via panel                    | DB-direct access reads them; no PII-redaction at write-time |
| ML block decisions with full path / query in `traffic_log` | RBAC limits panel surface to viewer+; no public read endpoint                | Anyone with ClickHouse credentials reads them; same DB-admin caveat |

### D — Denial of service

| Threat                                          | Mitigation                                                                                          | Residual                                                         |
|-------------------------------------------------|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| Login flood → argon2id CPU exhaustion           | 5/60s per `(IP, email)` rate-limit + fail-open on backend errors                                    | Single IP attacker with email-rotation can hit 5×N/60s, but each unique email is its own bucket; argon2id work parameters bound the ceiling |
| ml-service slow / down                          | Backend proxy has 20 ms timeout, fail-open response → UI shows `—`, ModSec keeps deciding           | Aggregate ml-service outage → no ML signal during the window; documented |
| Lua-subrequest amplifies request cost           | Lua subrequest budget 5 ms; nginx upstream timeouts capped; default flavour skips Lua entirely      | OpenResty flavour requires opt-in env var                        |
| AWS WAF UpdateIPSet abuse                       | 5-minute rate-limit floor; opt-in feature flag; fail-soft on AWS errors                             | Operator-triggered storm bounded by rate-limit                   |

### E — Elevation of privilege

| Threat                                          | Mitigation                                                                                | Residual                              |
|-------------------------------------------------|-------------------------------------------------------------------------------------------|---------------------------------------|
| `viewer` performs admin-only action             | Endpoint-level `Depends(require_role("admin"))` on every mutating endpoint                | Bug in the dependency injection would silently let calls through; mitigated by per-endpoint tests |
| Modify role through API                         | `users` table not exposed via REST; role changes are out-of-band (psql)                   | Acceptable for course project; production needs a managed user-admin endpoint |
| Container escape (proxy → host)                 | Out of scope for the panel; ModSec runs as `nginx` user, not root; no `--privileged`      | Standard Docker isolation              |
| Operator with host write swaps `ml.pkl` (joblib RCE) | Sprint-13 candidate: signed model artefacts; currently we trust the bind-mount             | Documented in §6 below                 |

## 4. Mitigation map → ADRs / code

| Mitigation                                  | Where it lives                                                              |
|---------------------------------------------|-----------------------------------------------------------------------------|
| Login rate-limit                            | `backend/src/waf_panel/security_rate_limit.py` + `api/auth.py`              |
| JWT-secret startup guard                    | `backend/src/waf_panel/main.py::_validate_settings`                          |
| RBAC                                        | `backend/src/waf_panel/api/auth.py::require_role`                            |
| Audit log                                   | `repositories/{memory,pg}.py::AuditRepo`, used by every mutating service     |
| ML kill-switches (UI / env / flavour)       | `infra/nginx/lua/score.lua`, `MlThresholdSlider`, ADR-0011                  |
| Drift detection                             | `backend/src/waf_panel/workers/drift_worker.py` + ADR-0009                  |
| AWS fail-soft + rate-limit                  | `backend/src/waf_panel/integrations/aws_waf.py` + ADR-0012                  |
| Fail-open ML inference                      | `backend/src/waf_panel/api/ml.py` + `ml-service/src/.../main.py` + ADR-0008 |
| OpenResty + Lua opt-in                      | `proxy/Dockerfile.openresty`, `infra/nginx/templates/openresty.conf.template` |

## 5. Out-of-scope (intentional)

* Network-layer DDoS (Cloudflare / AWS Shield is the right tool).
* OS-level hardening (Docker daemon, kernel, container runtime).
* Insider attacks by an operator with full host / DB access.
* Supply-chain attacks against `pip` / `npm` packages (we lock versions
  in `pyproject.toml` / `package-lock.json`; deeper SCA is Sprint-13+).

## 6. Known gaps / Sprint-13+ candidates

1. **Login enumeration timing.** Email-not-found path skips argon2id;
   fix by hashing a dummy on the missing-email branch.
2. **Default admin row.** Production startup guard checks `JWT_SECRET`
   but not the seeded `admin / admin` row.
3. **mTLS between containers.** Backend ↔ ml-service is plain HTTP.
4. **Joblib pickle execution risk.** Bind-mounted `.pkl` files run
   arbitrary code on `joblib.load`. Mitigation: signed-artefact verify
   against the registry's `model_version` checksum before load.
5. **Distributed brute-force across IPs.** Per-IP rate-limit dilutes;
   need account-level (or fail2ban-style) counter.
6. **Security-headers middleware** (CSP, HSTS, X-Frame-Options, X-Content-Type-Options).
7. **DB-admin tampers with `audit_log`.** Append-only contract
   enforced only at the API layer; production needs a write-only DB
   role for the backend and a separate read role for analysts.

## 7. Review cadence

Reviewed at every CP closure (Sprint 4 / 8 / 10) and after every
post-audit hotfix sprint. Next review: when blocking-mode actually
flips on (Sprint 13+, after CSIC-calibrated FPR-budget proof).
