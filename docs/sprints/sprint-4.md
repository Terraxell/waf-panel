# Sprint 4 — Frontend skeleton (week 5)

- Window: week 5 of the 12-week roadmap
- Driver: stand up the React panel — themed by `design-system.md`, capable
  of authenticating against the FastAPI gateway, displaying a placeholder
  dashboard, and routable as a real SPA.

## Definition of Done

- [ ] Vite + React 18 + TypeScript project initialises and builds clean.
- [ ] Theme is implemented as CSS custom properties matching `design-system.md`
      exactly (4-colour palette, Fraunces / Geist / JetBrains Mono, 0 radius).
- [ ] At least three reusable UI primitives: `Button`, `Input`, `Card`.
- [ ] Login page calls `POST /api/v1/auth/login`, stores the JWT in memory,
      redirects to the dashboard on success and surfaces 401 errors inline.
- [ ] Dashboard placeholder pulls `GET /api/v1/auth/me` and renders three
      stat cards: rules total, incidents (24h), recent audit (5 last rows).
- [ ] React Router covers `/login`, `/`, `/rules`, `/incidents`, `/audit`
      with a guard that redirects unauthenticated users to `/login`.
- [ ] `tsc --noEmit`, `vite build`, and `eslint` are green.
- [ ] `frontend` service joins `docker-compose.yml` with hot-reload bind
      mount in dev profile.

## Constraints driven by the methodology

- Item 13 — "современный стек на клиенте": React 18 + TS + Vite is the
  canonical 2025 stack. We avoid Tailwind on purpose so that the dist
  CSS is small and inspectable from the defence laptop.
- Item 9 — "качественные иллюстрации": the panel ships with the same
  design tokens used in the презентация, so screenshots and slides keep
  visual consistency.

## Out of scope

- Persistent auth (sessionStorage / refresh tokens) — Sprint 9.
- Recharts dashboards with real ClickHouse data — Sprint 6.
- The rules editor UI is a card with a "coming up next sprint" stub.
- Tests on the frontend — kept minimal for this sprint (one component
  test for the login form). Playwright e2e lands in Sprint 6.

## Notes

### Why no Tailwind?

The `design-system.md` palette is four colours, the type scale is fixed,
and we have a dedicated styling style ("один акцент на экран"). Pulling
in Tailwind to author six unique screens is overkill; vanilla CSS plus
custom properties keeps the dist under 30 KB and the rules in one place.

### Why React Router and not the Next.js app router?

Next.js fits a fullstack Node app; we already have FastAPI as the API
backend. A simple SPA with React Router is the lowest-friction option.
It also lets the same `dist/` ship behind nginx — same `Dockerfile`
multi-stage we use for the backend.

### Why store the token in memory only?

Two reasons. First, the panel is a thick client used by ops staff — the
session can be short and re-login is cheap. Second, sessionStorage and
localStorage make XSS recovery harder; in Sprint 9 we move to an
HTTP-only cookie set by the backend and bypass JS storage entirely.

## Carry-over to Sprint 5

- Replace memory-only token with an HTTP-only cookie issued by `/auth/login`.
- Wire React Query (or SWR) for cache and request dedup once we have
  more than one read endpoint per page.
