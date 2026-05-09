# ADR-0002 — Repository pattern and async DB sessions

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev
- Supersedes: nothing

## Context

Sprint 3 promotes the gateway from "stub with in-memory dicts" to a proper
service with PostgreSQL persistence. That decision introduces three
risks:

1. **Test speed.** A live database in the test loop kills the inner-dev
   feedback. The sandbox the project targets does not even have Docker.
2. **Coupling.** If endpoints call SQLAlchemy directly, swapping the
   storage engine — even for one test, even for one A/B — means surgery
   across the whole API surface.
3. **Audit consistency.** A mutation and its audit row must succeed or
   fail together; otherwise the audit trail diverges from reality.

## Decision

We use the **repository pattern** with two concrete implementations:

- `pg.PgRulesRepository`, `pg.PgUsersRepository`, `pg.PgAuditRepository`
  — async SQLAlchemy 2.x against PostgreSQL. Production path.
- `memory.InMemoryRulesRepository`, `memory.InMemoryUsersRepository`,
  `memory.InMemoryAuditRepository` — process-local dicts. Test path.

Both implementations satisfy a `Protocol` defined in
`waf_panel.repositories.base`. Endpoints do not import either concrete
class; they take the protocol via `Depends`.

Sessions are created **once** per request by a FastAPI dependency that
wraps `async_sessionmaker`. The dependency yields the session and commits
on a clean exit, rolls back on exception. This is the only place where
`AsyncSession` is constructed in the whole codebase.

Audit and mutation share one session, so `commit()` is a single atomic
unit. We do not use `Session.flush()` for "soft" durability — only commit
or rollback.

## Alternatives considered

- **Active Record on SQLAlchemy models.** Rejected. Tests would have to
  configure a live engine; we lose the test/prod split.
- **Direct asyncpg without an ORM.** Rejected. Manual SQL would explode
  the surface for a project at this scale; ORM is a net cost saver here.
- **Two-phase commit between Postgres and the in-memory store.**
  Rejected as overkill. The audit row lives in the same Postgres database
  as the rule; one transaction is enough.

## Consequences

- The whole API stays decoupled from SQLAlchemy. Mocking is trivial.
- The repository protocol now has to be kept in sync across two
  implementations. We pin the contract in `tests/test_repos.py` so any
  drift fails CI.
- Future Postgres-only features (e.g., `LISTEN/NOTIFY` for live config
  reload) cannot live behind the abstraction; they need their own narrow
  interface.

## Follow-ups

- ADR-0003 — Online/offline split for the ML service.
- Consider a `redis`-backed audit log mirror for tamper-evident retention
  in Sprint 9.
