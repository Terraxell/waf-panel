# ADR-0014 — httpOnly cookie auth + double-submit CSRF

- Status: Accepted
- Date: 2026-05-19
- Author: Gennadii Panteleev

## Context

Until now the panel authenticated browser sessions with a Bearer JWT
returned by `POST /auth/login` and stored in the SPA's in-memory state.
The token was sent on every API call via `Authorization: Bearer …`.

Two real problems, both flagged in the post-release security audit:

1. **In-memory storage doesn't survive page reload.** The user has to
   log in on every refresh, and on every browser restart. That is mild
   UX pain but enough to push operators toward asking for "remember
   me" — which usually ends in `localStorage`, which is XSS-stealable.

2. **Bearer in JS is reachable from JS.** Any future XSS (e.g. an
   unsanitised audit payload rendered as HTML) gives the attacker the
   token directly. CSP and the Sprint-13 security headers narrow the
   exposure but don't close it; a realistic threat for a panel that
   ingests attacker-controlled input by design.

We need a session mechanism the JS context cannot read but the browser
will keep across reloads. The standard answer is an httpOnly cookie.
The standard companion to that is double-submit CSRF protection.

## Decision

### Two auth paths, picked by client kind

The panel has two legitimate clients:

- **Browser SPA** — gets the cookie path. Subject to CSRF.
- **CLI / CI / curl / scripts** — keeps the Bearer path. Not subject
  to CSRF (no implicit credential).

`POST /auth/login` does **both** in a single request:
- Returns the access token in JSON (CLI keeps using it as before).
- Sets an httpOnly `waf_session` cookie carrying the same JWT.

The `current_user` dependency tries the cookie first, falls back to
`Authorization: Bearer …` if missing. Tests can keep using the Bearer
path; production browsers automatically pick up the cookie.

### Cookie attributes

```
Set-Cookie: waf_session=<JWT>;
            HttpOnly;
            SameSite=Strict;
            Path=/;
            Max-Age=<jwt_ttl_seconds>;
            Secure        # only when scheme == https
```

Trade-offs:

- **HttpOnly**: cookie is invisible to JS — closes the XSS-stealing
  vector. Required.
- **SameSite=Strict**: cookie is not sent on cross-site requests.
  Strong CSRF protection on its own, but we add the double-submit
  token below as defence-in-depth (browsers vary; SameSite is not
  universally supported on legacy mobile UA).
- **Secure** is conditional: in dev (http://localhost:3000) the
  browser would refuse to set a Secure cookie, breaking the local
  flow. We emit Secure only when the request scheme is `https`.
- **Path=/** so the cookie reaches `/api/v1/…` and `/api/openapi.json`.

### Double-submit CSRF token

A second cookie, `waf_csrf`, holds a 32-byte URL-safe random token.
The SPA reads it from `document.cookie` (this cookie is **not**
httpOnly — by design) and echoes it back in `X-CSRF-Token` on every
mutating request (POST/PUT/PATCH/DELETE).

The middleware compares: `cookie value == header value`. If they
don't match, 403. The cookie+header pair refreshes on login and on
every successful CSRF endpoint hit.

WHY this scheme rather than synchroniser-token-pattern: double-submit
keeps the server stateless — no per-session CSRF storage. Cookie+
header equality is enough as long as cookies cannot be set
cross-origin for our domain (which `SameSite=Strict` enforces and
the security headers' CSP backstops).

### CSRF skip rules

The middleware skips:

- **Safe methods** (GET, HEAD, OPTIONS) — no state mutation.
- **Bearer-authenticated requests** — no implicit cookie credential
  to abuse, so CSRF is moot. Detected by presence of
  `Authorization: Bearer …` and absence of `waf_session` cookie.

This keeps CLI/CI flows unchanged.

### Frontend impact

- `api.ts` adds `credentials: 'include'` so the cookie auto-attaches.
- For mutating verbs, the wrapper reads `waf_csrf` from
  `document.cookie` and adds `X-CSRF-Token`.
- `auth.ts` no longer holds a JWT. It holds the *CSRF token* (in
  memory), which is read once after login and kept in sync via the
  cookie on each `/auth/me` call.
- `Login.tsx` ignores `access_token` from the JSON response — the
  cookie is what matters now. The token in the body stays for CLI.
- `subscribe(listener)` keeps notifying the App shell when auth state
  changes; the gate is `isAuthenticated()` which now means "we have a
  CSRF token in memory", set after a successful `/auth/me`.

## Consequences

Positive:
- XSS no longer steals the session.
- Sessions persist across reloads.
- CLI flow unchanged (CI tests, smoke scripts, recruiter `curl`
  examples in README).

Negative:
- One more endpoint (`/auth/csrf`) to fetch the token after a hard
  refresh that doesn't go through `/auth/login`.
- Tests that hit mutating endpoints from a browser-style cookie
  client need a CSRF header. Backend tests using the `TestClient`
  with the Bearer path are unaffected.
- Cookie attributes diverge between dev (Secure off) and prod
  (Secure on). One conditional, one comment.

## Alternatives considered

- **localStorage + Bearer** — what most SPAs ship. Rejected because
  XSS-readable. The whole point of this ADR.
- **Synchroniser-token-pattern (server-side CSRF storage)** — strictly
  more secure than double-submit but requires per-session state in
  Redis/Postgres. Overkill for a course-project-scoped panel.
- **Cookie only, no CSRF token** — relying purely on `SameSite=Strict`.
  Rejected: defence-in-depth justifies the small extra weight, and the
  audit explicitly flagged "no CSRF" as a gap.

## Follow-ups

- ADR-0015: refresh-token rotation if we ever want long-lived sessions.
- Frontend: a `useCsrf()` hook for any future imperative form posts.
- Backend: if multi-tenant, cookie path should narrow per tenant.
