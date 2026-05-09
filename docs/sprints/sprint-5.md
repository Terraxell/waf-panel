# Sprint 5 — Real metrics, incidents, and React Query (week 6)

- Window: week 6 of the 12-week roadmap
- Driver: connect the dashboard cards to **real** ClickHouse aggregates,
  add the incidents page with filters, and graduate the frontend from
  hand-rolled fetch to React Query.

## Definition of Done

- [ ] Backend has an async ClickHouse client behind a Depends-injectable
      `ClickHouseDep`. The HTTP endpoints depend on the protocol, not the
      concrete client — same repository pattern we used for Postgres.
- [ ] `GET /api/v1/metrics/overview` returns four counters and a `top_attacks`
      list aggregated from `traffic_log`.
- [ ] `GET /api/v1/metrics/timeseries?bucket=minute&since=24h` returns a
      time-series of RPS and blocked-share, ready for Recharts.
- [ ] `GET /api/v1/incidents` returns paginated incidents with filters
      `since`, `until`, `ip`, `severity`, `decision`.
- [ ] Frontend uses `@tanstack/react-query` for fetch+cache; dashboard
      cards show live numbers, refreshing every 30 s.
- [ ] New page `/incidents` lists incidents with the filter bar.
- [ ] Recharts renders a small RPS line and a stacked blocked vs. allowed
      bar on the dashboard.
- [ ] Backend test suite green (≥ 25 tests), `ruff check` clean.
- [ ] Frontend `tsc --noEmit` clean, `eslint src --max-warnings 0` clean.

## Out of scope

- Materialized views in ClickHouse — dashboards still query raw `traffic_log`.
  Sprint 6 promotes hot queries to MVs once we know the actual shapes.
- HTTP-only cookie authentication — Sprint 9.
- Auto-generated TS types from OpenAPI — see ADR-0004; planned for the
  next ML-heavy sprint when the API stops moving as fast.

## Test matrix this sprint adds

| Suite                       | What it asserts                                                    |
|-----------------------------|--------------------------------------------------------------------|
| `tests/test_clickhouse.py`  | In-memory ClickHouse mock matches the protocol the API expects.    |
| `tests/test_metrics.py`     | `/metrics/overview` returns the documented shape, RBAC respected.  |
| `tests/test_incidents.py`   | Filters apply correctly; pagination caps work; auth required.      |

## Carry-over to Sprint 6

- Recharts area-chart for blocked-share with hover tooltips.
- ClickHouse materialized views for RPS-per-minute and top-attacks.
- Rules editor with CodeMirror + CRS-DSL highlight.
- Audit-log page (read-only table).
