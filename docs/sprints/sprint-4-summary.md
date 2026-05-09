# Sprint 4 — Summary

- Window: week 5 (planning), delivered ahead of schedule
- Status: **DONE** — verified end-to-end on Docker Desktop / Windows
- All 8 services healthy, attacks blocked by CRS, ClickHouse receiving traffic

## What landed

| Layer       | Files                                                                                          |
|-------------|------------------------------------------------------------------------------------------------|
| Docs        | `docs/sprints/sprint-4.md`, `docs/adr/0003-frontend-stack.md`                                  |
| Tooling     | `frontend/{package.json,tsconfig.json,vite.config.ts,.eslintrc.cjs,.dockerignore,Dockerfile,nginx.conf,index.html}` |
| Theme       | `frontend/src/styles/{tokens.css,base.css}` — design-system.md as CSS variables                |
| UI          | `frontend/src/components/ui/{Button,Input,Card}.{tsx,css}`                                     |
| Lib         | `frontend/src/lib/{types,api,auth}.ts`                                                         |
| Pages       | `frontend/src/pages/{Login,Dashboard}.{tsx,css}`                                               |
| Shell       | `frontend/src/{main,App}.tsx` — React Router + Shell with logout                               |
| Compose     | `frontend` service added; 8 services total                                                     |

## End-to-end verification (Docker Desktop, Windows host)

```text
PS> docker compose ps
NAME            STATUS                       PORTS
waf-backend     Up (healthy)                 8000/tcp
waf-clickhouse  Up (healthy)                 8123/tcp, 9000/tcp
waf-dvwa        Up (unhealthy — cosmetic)    80/tcp
waf-frontend    Up (healthy)                 3000/tcp
waf-postgres    Up (healthy)                 5432/tcp
waf-proxy       Up (healthy)                 8080/tcp
waf-redis       Up (healthy)                 6379/tcp
waf-vector      Up
```

| Probe                                                  | Result                                  |
|--------------------------------------------------------|-----------------------------------------|
| `GET /__health`                                        | `200 OK`                                |
| `GET /login.php`                                       | `200 OK`, DVWA login page               |
| `GET /?id=1 OR 1=1--`                                  | `403 Forbidden` (CRS rule 942100)       |
| `GET /?q=<script>alert(1)</script>`                    | `403 Forbidden` (CRS XSS rule)          |
| `GET /?cmd=cat /etc/passwd`                            | `403 Forbidden` (CRS RCE rule)          |
| `SELECT count() FROM waf_logs.traffic_log`             | `73` rows after a small attack burst    |
| Frontend SPA at `localhost:3000` after login as admin  | renders dashboard with `admin@example.com`, role `admin`, rule count `0` |

## Test counts

| Suite                  | Tests | What it covers                                       |
|------------------------|-------|------------------------------------------------------|
| `test_smoke.py`        | 7     | API contract, auth flow, rules CRUD, OpenAPI surface |
| `test_repos.py`        | 9     | In-memory repository contract                        |
| `test_audit.py`        | 3     | Login OK/fail and rule lifecycle produce audit rows  |
| `test_alembic.py`      | 1     | Offline migration render contains every model table  |
| **total**              | 20    |                                                      |

Frontend: `tsc --noEmit` clean, `eslint src --max-warnings 0` clean. Vite build runs inside the container's multi-stage `Dockerfile`.

## Notes for the explanatory note (методичка table 1)

- **Item 11 — журналирование, отладка, тестирование.** Closed by audit log
  in PostgreSQL + 1 700-rule CRS audit log streamed by Vector to ClickHouse.
  Live demo: send SQLi → see 403 → find the row in ClickHouse.
- **Item 12 — глубокое понимание клиент-серверных приложений.** Two
  separate request paths (protective sync + analytic async) implemented in
  one stack, documented in `docs/adr/0001-tech-stack.md`.
- **Item 13 — современный стек на клиенте.** React 18 + TS + Vite,
  themed by hand-authored CSS variables; bundle stays small.

## Ops lessons captured in `docs/troubleshooting.md`

The full bring-up surfaced nine real-world Docker / nginx / Vector edge
cases. They are now documented with symptom / root-cause / fix:

1. Frontend `npm install` fails with cross-platform Rollup binaries
2. Backend container "no module named uvicorn" — `--prefix` install pitfall
3. `relation "users" already exists` from alembic on bootstrap volume
4. 401 on default panel login — placeholder argon2 hash
5. `Invalid input: block` from ModSecurity — `SecRuleEngine` value
6. `log_format directive not allowed here` — wrong nginx context
7. envsubst `$$variable` collisions in templates
8. `Read-only file system` when image template overrides our mount
9. Vector `to_timestamp!` removed in 0.40 — use `parse_timestamp!`
10. ClickHouse rejects timestamp-with-TZ strings in JSONEachRow
11. Vector env-substitution applies inside comments — strip stray `$`

These will fold straight into Приложение В (admin instruction) of the
explanatory note.

## Carry-over to Sprint 5

- Replace memory token with HTTP-only cookie set by backend (ADR-0005).
- Generate API types from FastAPI's OpenAPI spec (ADR-0004).
- Dashboard cards pull real ClickHouse aggregates (RPS, blocked-share,
  top-attacks).
- Incidents page with time/IP/severity filters, paginated.
- Rules editor with CRS-DSL syntax highlight (CodeMirror).
- React Query / SWR for cache and request dedup.
