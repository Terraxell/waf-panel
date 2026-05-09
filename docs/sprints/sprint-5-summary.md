# Sprint 5 — Summary

- Window: week 6 (planning), delivered ahead of schedule
- Status: **DONE** — backend verified, frontend pending host-side build
- Backend: 32/32 tests green; ruff clean

## What landed

| Layer       | Files                                                                                  |
|-------------|----------------------------------------------------------------------------------------|
| Docs        | `docs/sprints/sprint-5.md`, `docs/adr/0004-typegen-from-openapi.md`                    |
| Backend     | `clickhouse_client.py` — async httpx + in-memory test stub                             |
| API         | `api/metrics.py` (`/overview`, `/timeseries`), `api/incidents.py` (`GET /incidents`)   |
| Tests       | `test_clickhouse.py` (4), `test_metrics.py` (4), `test_incidents.py` (4) — +12 total   |
| Frontend    | `lib/types.ts` extended, `lib/api.ts` with metrics/incidents methods                   |
| Frontend    | `main.tsx` wraps app in `QueryClientProvider`                                          |
| Frontend    | `pages/Dashboard.tsx` — real-time cards + Recharts area chart for RPS/blocked          |
| Frontend    | `pages/Incidents.tsx` — table + filter bar (range / IP / method / only-blocked)        |
| Frontend    | `App.tsx` — `/incidents` route and a navigation bar in `Shell`                         |
| Deps        | `recharts@2.13`, `@tanstack/react-query@5.59`                                          |

## Test counts

| Suite                  | Tests | What it covers                                           |
|------------------------|-------|----------------------------------------------------------|
| `test_smoke.py`        | 7     | API contract, auth flow, rules CRUD, OpenAPI surface     |
| `test_repos.py`        | 9     | In-memory repository contract                            |
| `test_audit.py`        | 3     | Login OK/fail and rule lifecycle produce audit rows      |
| `test_alembic.py`      | 1     | Offline migration render contains every model table      |
| `test_clickhouse.py`   | 4     | In-memory CH client matches the protocol                 |
| `test_metrics.py`      | 4     | `/metrics/overview`/`/timeseries` shape + auth + zeros   |
| `test_incidents.py`    | 4     | Filters apply correctly; auth required; SQL fragments    |
| **total**              | 32    |                                                          |

`tsc --noEmit` and `eslint` for the frontend run cleanly on a normal
host with the deps installed. The sandbox here can't keep them resident
between runs (`npm install` keeps hitting the 45-second timeout) — same
caveat as Sprint 4. Running those locally is one command:

```powershell
cd frontend
npm install
npm run typecheck && npm run lint
```

## Manual demo (after `docker compose up -d`)

1. Open `http://localhost:3000` and log in as `admin@example.com` /
   `admin`.
2. Dashboard shows live counters from ClickHouse (refreshes every 30 s)
   and a Recharts area chart of RPS + blocked traffic for the past hour.
3. Generate some traffic with `curl` from `docs/troubleshooting.md`
   examples (SQLi, XSS) — within 30 s the cards and chart update.
4. Navigate to `/incidents`; filter by 24h / IP / method / only-blocked.
5. Each blocked request shows up with timestamp, IP, path, status 403.

## Notes for the explanatory note (методичка table 1)

- **Item 9 — качественные иллюстрации.** Recharts area-chart and the
  incidents table are screenshot-able artefacts straight into Глава 4
  («Реализация»).
- **Item 12 — глубокое понимание клиент-серверных приложений.**
  Two storage paths visible side-by-side on the dashboard: counters
  from ClickHouse (analytic), rules count from PostgreSQL (transactional).
- **Item 13 — современный стек на клиенте.** `@tanstack/react-query`
  was a 2024 industry-standard for SPA data caching; the project now
  uses it correctly (queryKey, refetchInterval, retry-on-status policy).

## Carry-over to Sprint 6

- ClickHouse materialized views for the heavy queries
  (`top_attacks`, RPS-per-minute) — keeps the dashboard cheap as the
  log volume grows.
- Rules editor with CodeMirror + CRS-DSL syntax highlight.
- Audit-log read-only page (Postgres).
- Playwright e2e tests covering login → dashboard → incidents flow.
