# ADR-0004 — Plan to generate TypeScript types from OpenAPI

- Status: Proposed
- Date: 2026-05-08
- Author: Gennadii Panteleev

## Context

The frontend currently keeps a hand-written copy of the API surface in
`frontend/src/lib/types.ts`. As long as the backend was a stub it was
fine — the contract didn't move. From Sprint 5 onward the backend is
growing fast (metrics, incidents, rules editor, audit log), and any
manual sync between Pydantic models and TS types becomes a known source
of drift.

FastAPI already publishes a complete OpenAPI 3.1 schema at
`/api/openapi.json`. That schema is the single source of truth — it's
generated from the same Pydantic models the API uses for validation.

## Decision (proposed, not yet executed)

When the API surface stops moving (likely Sprint 7 once metrics +
incidents + rules editor stabilise), introduce automatic generation of
TypeScript types from the OpenAPI schema:

- **Tool:** `openapi-typescript` — the most-used Node CLI for this job,
  zero runtime, produces a single `*.ts` file with `interface`/`type`
  exports keyed off the OpenAPI `components.schemas` map.
- **Trigger:** `npm run gen:types` runs `openapi-typescript
  http://backend:8000/api/openapi.json -o src/lib/api-types.ts`.
- **Workflow:** the generated file is committed to the repo and
  refreshed by the developer who changes the backend. CI runs the same
  command on the schema dumped by a one-shot test container, then
  `git diff --exit-code src/lib/api-types.ts` — if anything is out of
  sync, CI fails.

## Why not now

- Sprint 5 still adds new endpoints and reshapes existing ones every
  day. Regenerating after each change creates noise and breaks the build
  loop.
- Manual types in `lib/types.ts` are a few dozen lines today. The cost
  of a temporary hand-sync is lower than the cost of fighting
  generation tooling on a moving target.

## Alternatives considered

- **`@hey-api/openapi-ts`** — newer, more featureful (also generates a
  typed client). Rejected for now: extra surface area, our own fetch
  wrapper is simple and close enough to what we want. Reconsider when
  we add streaming or WebSocket endpoints.
- **`tRPC`** — would replace OpenAPI entirely with a type-safe RPC.
  Rejected: it would force the frontend to live in the same monorepo
  build with the backend, which we explicitly didn't want (Python
  backend, Node frontend, separate Dockerfiles).
- **No generation, hand-roll forever** — fine for a 5-endpoint demo,
  not for the final defence-time API surface (~25 endpoints).

## Consequences when executed

- `frontend/src/lib/types.ts` becomes a re-export of selected types
  from the generated `api-types.ts` plus any frontend-only domain types.
- CI gets a new job (`frontend-types-check`) that fails on drift.
- New backend endpoint: 30 seconds — write Pydantic models, run
  `npm run gen:types`, commit. No more hand-editing TS.

## Follow-ups

- ADR-0005 — HTTP-only cookie auth (Sprint 9).
- ADR-0006 — ClickHouse materialized views for hot dashboard queries
  (Sprint 6).
