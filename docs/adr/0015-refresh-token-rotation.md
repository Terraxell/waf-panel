# ADR-0015 — Refresh-token rotation

- Status: Accepted
- Date: 2026-05-26
- Author: Gennadii Panteleev

## Context

ADR-0014 ships cookie + double-submit CSRF. The session JWT lives in
the `waf_session` cookie with a fixed `jwt_ttl_minutes` (default 60).
When that hits zero the user is bounced to /login mid-session. For a
panel an operator stares at all day, that's friction; for the demo
deploy it's a minor annoyance, but the moment we move to a real
production tenant it becomes the #1 complaint.

The standard fix is **token rotation**: issue a short-lived access
token (5–15 minutes) plus a longer-lived refresh token (days), and
trade the refresh for a new pair when access expires. This keeps the
window of a stolen access token small without forcing the user to
re-auth every hour.

Two design choices follow from picking rotation:

1. **Where the refresh lives** — separate cookie scoped to one path,
   so XSS that bypasses `waf_session`'s httpOnly (it can't, but
   defence in depth) still can't read the refresh.
2. **Replay detection** — what happens when the SAME refresh token
   is presented twice. The naive answer is "issue a new pair every
   time"; the better answer detects the second use as proof of theft
   and revokes the whole family.

## Decision

### Two tokens, two scopes

| Token   | TTL        | Cookie name      | Path scope         | httpOnly |
|---------|------------|------------------|--------------------|----------|
| access  | 15 min     | `waf_session`    | `/`                | yes      |
| refresh | 14 days    | `waf_refresh`    | `/api/v1/auth/`    | yes      |

The access token is unchanged in shape from ADR-0014 (FastAPI
dependencies still read `waf_session`). The refresh token is new
and scoped to `/api/v1/auth/` so the browser only sends it on the
auth endpoints — that limits the blast radius of any path that
reflects request headers.

### Refresh-family table (server-side state)

```sql
CREATE TABLE refresh_token_families (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    generation  INT  NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ
);
```

A refresh JWT carries `family_id` + `generation` in its claims. On
`/auth/refresh`:

1. Decode the refresh JWT.
2. Look up the family. If not found OR `revoked_at IS NOT NULL` →
   reject (401).
3. If `claims.generation < family.generation` — **the same family is
   being used in an out-of-order generation, which means a token was
   reused or stolen**. Revoke the family (`revoked_at = now()`),
   reject (401).
4. Otherwise: bump `family.generation`, set `last_used_at`, issue a
   new access + refresh pair with the new generation. Return.

Logout clears both cookies and revokes the family.

### Replay scenario, walked through

User legitimately holds refresh `(family=F, gen=5)`. Attacker steals
this token (cookie XSS, network capture, malware). Two paths:

- **User refreshes first:** server rotates to `gen=6`, attacker's
  `gen=5` is now stale. When attacker presents `gen=5`, server sees
  `5 < 6`, marks `revoked_at`, both parties get bounced to /login.
  User notices something off, rotates their password.
- **Attacker refreshes first:** server rotates to `gen=6`. User's
  next refresh presents `gen=5`. Same outcome.

Either way the second refresh of the stolen token revokes the
family. The window for silent abuse is one rotation cycle (15 min).

### What this does NOT solve

- **Pure access-token theft.** The access JWT still works for 15 min.
  This is a deliberate trade-off — rotating access tokens on every
  request would double the latency and require server-side state
  per request.
- **Compromised JWT_SECRET.** A leaked secret means the attacker
  forges access tokens at will. Mitigated by the existing JWT secret
  rotation runbook (section 7).
- **Stolen device.** If the attacker has the user's browser, they
  have the refresh too. Out of scope for a panel.

## Consequences

Positive:

- Operators don't get bounced to /login every hour during a long
  session — refresh extends the working day silently.
- Stolen-refresh attacks self-revoke on the next legitimate refresh.
- The refresh family ID is a useful audit pivot: "show me all
  family revocations in the last 24 h" surfaces real abuse.

Negative:

- One more table, one more migration (`0004_refresh_token_families`).
- Frontend gains a 401-retry-with-refresh path in `api.ts`. Tests get
  longer.
- Logout now has to do an extra DB write to revoke the family.

Net: this is the standard trade-off SaaS panels accept once they
hit the "users keep getting logged out" pain point. The complexity
is contained.

## Alternatives considered

- **Sliding session.** Re-issue a fresh access JWT on every request.
  Simpler, but means access tokens have no real expiry from the user's
  perspective — a stolen access JWT works forever as long as the
  attacker keeps using it.
- **Server-side session ID + Redis store.** Classical PHP-shaped
  approach. Works, but throws away the stateless-JWT property and
  pulls Redis onto the auth path.
- **No rotation at all.** What we shipped in 1.0. Fine for course
  defence; not fine for a 9-to-5 operator.

## Migration & rollout

- Migration `0004_refresh_token_families` adds the table, no data
  changes.
- The login endpoint and `/auth/refresh` are added in the same
  release. Existing access tokens issued before the upgrade still
  work until `jwt_ttl_minutes` expires.
- The frontend gains a retry-on-401 hook; pre-upgrade SPAs gracefully
  fall back to /login on token expiry as before.

## Follow-ups

- ADR-0016: per-device session list + remote sign-out from the panel.
- Telemetry: emit `auth.refresh.replay_revoked` audit rows so a
  revocation spike triggers operator review.
- `last_used_at` exposed in the user profile UI ("active sessions").
