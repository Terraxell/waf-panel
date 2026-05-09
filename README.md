# waf-panel

[![ci](https://github.com/Terraxell/waf-panel/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Terraxell/waf-panel/actions/workflows/ci.yml)
[![release](https://img.shields.io/badge/release-v1.0.0-2A4DB8)](./CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-163%20passing-2A4DB8)](./CHANGELOG.md)

Web Application Firewall management dashboard with an ML-based anomaly
detector. Course project at IEML, "Internet Programming" discipline
(variant #14, extended).

ModSecurity + OWASP CRS catches known attack patterns. XGBoost +
Isolation Forest catches what the rules miss. One panel manages both.

## Status

v1.0.0 ships everything from the 12-week roadmap. Ten services boot
via `docker compose up -d`. ModSecurity blocks SQLi, XSS and RCE on
the request path. Vector ships traffic events into ClickHouse. The
dashboard, rule editor and audit log all work.

The offline ML pipeline (`make train`) trains LR, XGBoost and
IsolationForest on a stratified split with 5-fold CV, then registers
them into Postgres `ml_models`. Online inference runs in a separate
`ml-service` container behind a fail-open backend proxy
(`POST /api/v1/ml/inspect`, 20 ms p99 timeout).

Later releases added drift detection (PSI + KS over all 25 features),
per-prediction contributors (`POST /api/v1/ml/explain`), threshold
calibration, opt-in block-mode via Lua subrequest
(`PROXY_FLAVOR_DOCKERFILE=Dockerfile.openresty`), an attack-bench
harness with 200 labelled probes, an opt-in AWS WAF IPSet adapter,
the drift worker on a schedule, and a UI in RU / EN / DE / FR.

Full history: `CHANGELOG.md`.

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

Default panel login: `admin@example.com` / `admin`. Rotate it via the
API or psql before any non-dev usage.

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
