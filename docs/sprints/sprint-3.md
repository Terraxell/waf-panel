# Sprint 3 — Persistence and audit (week 4)

- Window: week 4 of the 12-week roadmap
- Driver: replace the in-memory `_store` with a real PostgreSQL-backed
  repository, gain an audit trail, and prepare the schema for migrations so
  that future sprints can edit it without dropping the volume.

## Definition of Done

- [x] SQLAlchemy 2.x async models mirror `infra/postgres/init.sql` exactly.
- [x] Async session is provided by FastAPI lifespan, never created per request.
- [x] Repository abstraction has at least two implementations:
      Postgres-backed and in-memory (the latter keeps tests fast and
      Docker-free).
- [x] Every mutating endpoint writes a row into `audit_log` in the same
      transaction as the mutation itself.
- [x] Alembic is wired in. The first revision matches the bootstrap schema
      so a fresh stack and a fresh migration produce the same database.
- [x] `ruff check` clean, full pytest suite green.

## Notes

### Why a repository abstraction at this stage?

Our smoke tests run on Python 3.10 in a sandbox without Docker. If the
backend talked to PostgreSQL directly inside test code, every CI run would
need a live database. The repository interface lets us inject the
in-memory variant during tests and the real one in production, so the
test loop stays under a second.

### Why audit log inside the same transaction?

Two reasons. First, audit is a security artefact — if it can drift from
the actual state of the rules table, it is worse than no audit. Second, the
methodology table 1, item 11 — "журналирование, отладка, тестирование" —
expects evidence of structured logging, not just `print`.

### Why Alembic on top of an init.sql that already does the work?

`init.sql` runs once on first volume creation. Any change later requires
either dropping the volume (kills user data) or hand-rolled SQL (rotates
between developers and breaks repeatability). Alembic gives us the path
forward: from Sprint 4 onward, schema changes go through `alembic revision`
and `alembic upgrade`. The first revision is generated to match the
bootstrap so existing volumes can be stamped.

### Out-of-scope for this sprint

- Refresh tokens and MFA — Sprint 9.
- Permissioned API keys for the gateway-to-ML calls — Sprint 7.
- Postgres `CITEXT` for emails outside dev — left as the Sprint 9 hardening
  task because we want the email-validator behaviour to drive shape first.

## Test matrix this sprint adds

| Suite                        | What it asserts                                               |
|------------------------------|---------------------------------------------------------------|
| `tests/test_repos.py`        | Repository contract: in-memory implements every method.       |
| `tests/test_audit.py`        | Mutating endpoints leave an `audit_log` entry.                |
| `tests/test_alembic.py`      | Migration head matches the SQLAlchemy metadata fingerprint.   |

## Carry-over to Sprint 4

- Wire backend container into `docker-compose.yml` (Sprint 4 boots end-to-end).
- Add a `make migrate` target that runs `alembic upgrade head` against the
  running Postgres container.
