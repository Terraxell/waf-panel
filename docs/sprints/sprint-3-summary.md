# Sprint 3 — Summary

- Window: week 4 (planning), delivered ahead of schedule
- Status: **DONE**
- Verification: ruff clean, 20/20 pytest green, alembic offline render produces
  the full schema, docker-compose syntax valid

## What landed

| Layer       | Files                                                                                          |
|-------------|------------------------------------------------------------------------------------------------|
| Docs        | `docs/sprints/sprint-3.md`, `docs/adr/0002-repository-and-sessions.md`                         |
| ORM         | `backend/src/waf_panel/db/{base,models,session}.py`                                            |
| Repos       | `backend/src/waf_panel/repositories/{base,memory,pg,deps}.py`                                  |
| Services    | `backend/src/waf_panel/services/{auth_service,rules_service}.py`                               |
| Migrations  | `backend/alembic.ini`, `backend/alembic/{env.py,script.py.mako}`, initial revision `0001`      |
| API         | `backend/src/waf_panel/api/{auth,rules}.py` rewritten on top of services + repos               |
| Tests       | `backend/tests/{test_repos,test_audit,test_alembic}.py`                                        |
| Compose     | `backend` service added to `docker-compose.yml` with healthcheck and env wiring                |
| Make        | `make migrate`, `make migrate-revision MSG="..."`                                              |
| Image       | `backend/Dockerfile` now ships `alembic/` and `alembic.ini`                                    |

## Test counts

| Suite                  | Tests | What it covers                                         |
|------------------------|-------|--------------------------------------------------------|
| `test_smoke.py`        | 7     | API contract, auth flow, rules CRUD, OpenAPI surface   |
| `test_repos.py`        | 9     | In-memory repository contract                          |
| `test_audit.py`        | 3     | Login OK/fail and rule lifecycle produce audit rows    |
| `test_alembic.py`      | 1     | Offline migration render contains every model table    |
| **total**              | **20**|                                                        |

## Notes for grading (методичка table 1, items 11–12)

- Item 11 — "журналирование, отладка, тестирование": closed by audit log
  in PostgreSQL (`audit_log` table) plus `tests/test_audit.py` proving the
  trail.
- Item 12 — "глубокое понимание клиент-серверных приложений": the
  service/repository split now demonstrates separation of transport,
  domain logic, and persistence. Сoncrete artefact for the defence is
  ADR-0002 plus the test contract in `tests/test_repos.py`.

## Сarry-over to Sprint 4

- Wire React frontend skeleton (Vite + TS + design tokens from
  `design-system.md`).
- Sprint 4 will not need DB schema changes, so existing migrations stay
  authoritative.
- Add OpenTelemetry traces from `httpx` calls if we end up calling the ML
  service over HTTP — keep until the ML container actually exists.
