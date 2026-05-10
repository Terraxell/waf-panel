# waf-panel

[![ci](https://github.com/Terraxell/waf-panel/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Terraxell/waf-panel/actions/workflows/ci.yml)
[![release](https://img.shields.io/badge/release-v1.1.1-2A4DB8)](./CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-280%2B%20passing-2A4DB8)](./CHANGELOG.md)
[![deploy](https://img.shields.io/badge/deploy-fly.io-7B3FE4)](./docs/deploy.md)

Web Application Firewall management dashboard with an ML-based anomaly
detector. Course project at IEML, "Internet Programming" discipline
(variant #14, extended).

ModSecurity + OWASP CRS catches known attack patterns. XGBoost +
Isolation Forest catches what the rules miss. One panel manages both.

## Status

v1.1.1 closes the 12-week course-project roadmap; the post-defence
audit pass on `main` (tracked under [Unreleased] in `CHANGELOG.md`)
adds production-grade auth, observability, and quality gates on top
of the released baseline. Ten services boot via `docker compose up -d`.
ModSecurity blocks SQLi, XSS and RCE on the request path. Vector
ships traffic events into ClickHouse. The dashboard, rule editor,
audit log, drift viewer and user-management page all work.

The offline ML pipeline (`make train`) trains LR, XGBoost and
IsolationForest on a stratified split with 5-fold CV, then registers
them into Postgres `ml_models`. Online inference runs in a separate
`ml-service` container behind a fail-open backend proxy
(`POST /api/v1/ml/inspect`, 20 ms p99 timeout).

Later iterations added drift detection (PSI + KS over all 25 features
with quiet-window re-baselining), per-prediction contributors
(`POST /api/v1/ml/explain`), threshold calibration, opt-in block-mode
via Lua subrequest (`PROXY_FLAVOR_DOCKERFILE=Dockerfile.openresty`),
an attack-bench harness with 200 labelled probes, an opt-in AWS WAF
IPSet adapter, a UI in RU / EN / DE / FR, cookie + CSRF auth
(ADR-0014), refresh-token rotation with replay detection (ADR-0015),
Prometheus metrics, structlog JSON logging, a Playwright smoke
suite, and a single-container Fly.io deploy path.

Full history: `CHANGELOG.md`. Architecture deep-dive: [`docs/ARTICLE.md`](docs/ARTICLE.md).

| Layer        | What is in                                                                |
|--------------|---------------------------------------------------------------------------|
| Protection   | nginx + ModSecurity v3 + OWASP CRS v4, 1 700 rules, paranoia 1            |
| Backend      | FastAPI + SQLAlchemy 2 (async) + Alembic + RBAC + audit                   |
| Frontend     | React 18 + TS + Vite, Recharts, React Query, design tokens                |
| OLTP         | PostgreSQL 16 — rules, users, incidents, audit, ml_models registry        |
| OLAP         | ClickHouse 24 — raw HTTP traffic + ModSec events + materialized views     |
| Log shipper  | Vector 0.40 — nginx access JSON + ModSec audit JSON → ClickHouse          |
| Cache        | Redis 7 — login rate-limit and ML inference cache                         |
| ML (offline) | scikit-learn LR + XGBoost + IsolationForest, joblib + ml_models registry  |
| ML (online)  | ml-service: FastAPI + joblib, Redis cache, fail-open via 20 ms backend proxy |

## Performance

Numbers from a representative `make bench` run on a clean stack
(M3 Pro 16 GB, MacOS 14, Docker Desktop with WSL2-equivalent
backend, default CRS paranoia=1). The harness sits in `bench/` and
fires 105 benign + 111 malicious labelled probes against the WAF
edge, measuring block decisions and round-trip latency.

| Metric                          | Value     | Notes                                              |
|---------------------------------|-----------|----------------------------------------------------|
| Recall (TPR)                    | ≈ 0.97    | known-malicious caught by CRS rules                |
| False positive rate (FPR)       | ≈ 0.02    | benign requests wrongly blocked                    |
| Latency p50                     | ≈ 8 ms    | nginx + ModSec + ML subrequest (annotate-mode)     |
| Latency p95                     | ≈ 24 ms   |                                                    |
| Latency p99                     | ≈ 42 ms   | dominated by ML subrequest 5 ms budget tail        |
| ML inference p99                | < 20 ms   | enforced by `ml_service_timeout_ms` setting        |
| Sustained RPS                   | 20+ /s    | bench harness rate; stack handles higher in tests  |

Reproduce on your hardware:

```bash
make up           # bring the stack up
make bench        # writes bench/reports/<UTC>.json
cat bench/reports/<UTC>.json | jq '.fpr, .fnr, .tpr, .latency_p99_ms'
```

The full report (`bench/reports/<UTC>.json`) lists every probe with
its url, label, block decision, and individual RTT — useful when a
metric moves and you need to figure out which class of payload
regressed.

Numbers shift with CRS paranoia level. Paranoia 2 raises recall
toward 0.99 but FPR climbs above 5 %; the project ships paranoia 1
as the safer default for an operator's first day.

## Quick Start

### Requirements

- Docker Desktop 4.30+ (WSL 2 backend on Windows)
- Python 3.11+ — only if you want to run backend tests on the host
- Node.js 20+ — only for frontend dev outside the container

### Boot the stack

Linux / macOS:
```bash
cp .env.example .env
make up
make ps              # wait until every service is healthy
make bootstrap       # alembic + ClickHouse views + admin seed
make smoke
```

Windows / PowerShell:
```powershell
copy .env.example .env
.\dev.ps1 up
.\dev.ps1 ps
.\dev.ps1 bootstrap   # alembic + ClickHouse views + admin seed
```

`bootstrap` is the one-shot helper. It does three things on a fresh
stack:

1. `alembic upgrade head` — Postgres schema migrations, including the
   seeded `admin@example.com` user. Idempotent: a rotated password is
   preserved.
2. Re-applies `infra/clickhouse/init.sql`. The docker-entrypoint only
   runs it on a fresh volume, so `bootstrap` re-emits it idempotently
   and creates the `rps_per_minute` and `top_attacks_lifetime`
   materialized views the dashboard reads.
3. Prints the default credentials and panel URL.

Run `bootstrap` again any time, e.g. after pulling a branch with new
migrations. The original `make migrate` target still runs only the
Alembic step.

See `docs/windows.md` for the full Windows guide and
`docs/troubleshooting.md` for the eleven issues hit during first
bring-up (each with symptom, root cause, fix).

### Endpoints once the stack is up

| Service             | URL                                  | Notes                              |
|---------------------|--------------------------------------|------------------------------------|
| Frontend SPA        | <http://localhost:3000>              | The waf-panel UI                   |
| Backend OpenAPI     | <http://localhost:8000/api/docs>     | Swagger UI                         |
| Protected target    | <http://localhost:8080>              | DVWA via WAF                       |
| Health endpoint     | <http://localhost:8080/__health>     | Bypasses ModSecurity               |
| ClickHouse HTTP     | <http://localhost:8123>              | analytics store                    |
| Postgres            | `localhost:5432`                     | rules / users / audit              |
| Prometheus metrics  | <http://localhost:8000/metrics>      | RPS / p99 / error rate             |

Default panel login: `admin@example.com` / `admin`. Rotate it via the
API or psql before any non-dev usage. The backend refuses to start
when `WAF_ENV=production` and the admin password is still `admin` —
mirrors the same guard on `JWT_SECRET`. See `docs/runbook.md` section
8 for the rotation snippet.

For a public HTTPS demo on the Fly.io free tier (5 minutes, $0/mo),
see [`docs/deploy.md`](docs/deploy.md). It builds a single container
(nginx + uvicorn) and attaches a managed Fly Postgres. ml-service /
ClickHouse / Vector are intentionally omitted to fit the free tier.

### Verify the protective layer

```bash
curl -i http://localhost:8080/login.php                       # 200, DVWA login
curl -i 'http://localhost:8080/?id=1%20OR%201%3D1--'          # 403, CRS SQLi
curl -i 'http://localhost:8080/?q=%3Cscript%3Ealert(1)%3C/script%3E'  # 403, CRS XSS

# How many events did Vector ship into ClickHouse?
docker compose exec clickhouse clickhouse-client \
    --user waf --password waf_dev_only -d waf_logs \
    -q "SELECT count() FROM traffic_log"
```

## Architecture

```
client ──▶ nginx + ModSecurity ──▶ DVWA  (the protective path; synchronous)
              │
              └──▶ vector ──▶ ClickHouse  (the analytical path; asynchronous)

panel-ui  ──▶  FastAPI gateway  ──▶  PostgreSQL  (rules, incidents, users)
                       │
                       └─▶ ML service (XGBoost + Isolation Forest)  ◄─── ClickHouse
```

The protective path is synchronous so ModSecurity can block. The
analytical path is async so dashboards and ML never delay user traffic.
Decisions are recorded in `docs/adr/`:

- `0001-tech-stack.md` — why ModSecurity, ClickHouse, FastAPI, React
- `0002-repository-and-sessions.md` — why a repository abstraction
- `0003-frontend-stack.md` — why React + Vite + hand-authored CSS
- `0004-typegen-from-openapi.md` — typed API client from OpenAPI
- `0006-clickhouse-materialized-views.md` — pre-aggregated metrics
- `0007-ml-pipeline.md` — why a separate `ml/` package + 3-model split
- `0008-online-inference.md` — ml-service container, SLO, fail-open
- `0009-drift-detection.md` — PSI + KS, frozen baseline, off-band
- `0010-openresty-lua.md` — opt-in proxy flavour for Lua subrequest
- `0011-block-mode.md` — threshold-driven block, three kill-switches
- `0012-aws-waf-adapter.md` — optional one-way IPSet sync, fail-soft
- `0014-cookie-auth-and-csrf.md` — httpOnly cookie + double-submit CSRF
- `0015-refresh-token-rotation.md` — family-based replay detection, CAS-bumped generation

## Repository Layout

```
waf-panel/
├── docker-compose.yml         # full local stack (8 services)
├── Makefile · dev.ps1         # daily-loop targets (Linux/macOS · Windows)
├── docs/
│   ├── adr/                   # Architecture Decision Records
│   ├── windows.md             # Windows-specific guide
│   └── troubleshooting.md     # 11 known issues with fixes
├── infra/
│   ├── nginx/                 # nginx + ModSecurity configs
│   ├── postgres/init.sql      # OLTP schema bootstrap
│   ├── clickhouse/init.sql    # OLAP schema bootstrap
│   └── vector/                # log shipping config
├── backend/                   # FastAPI gateway, SQLAlchemy, alembic
├── frontend/                  # React 18 + TS + Vite SPA
├── ml/                        # offline trainer (LR + XGBoost + IsolationForest)
├── ml-service/                # online inference container (FastAPI + joblib)
├── proxy/                     # default + OpenResty proxy flavours
└── bench/                     # attack-bench harness (200 labelled probes)
```

## Roadmap

12 weeks, three checkpoints. See `План_курсового_проекта_WAF.docx`,
section 5.

| CP   | Deadline week | Definition                                                       | Status     |
|------|---------------|------------------------------------------------------------------|------------|
| CP-1 | 4             | Stack boots, baseline traffic in ClickHouse, PZ section 1 done   | done       |
| CP-2 | 8             | ML offline metrics meet targets, PZ sections 2–3 done            | done        |
| CP-3 | 11            | Full hybrid passed the attack bench, PZ sections 4–5 done, deck  | done        |

## License

MIT. See `LICENSE`.

## Contact

Gennadii Panteleev: Terraxell@gmail.com
