# ADR-0003 — Frontend stack and theming

- Status: Accepted
- Date: 2026-05-08
- Author: Gennadii Panteleev
- Supersedes: nothing

## Context

The defence rubric (методичка table 1, item 13) explicitly grades the
"modern stack on the client". The chosen frontend has to satisfy three
things: be type-safe, ship a small bundle, and respect the in-house
design system documented in `design-system.md` (four colours, Fraunces /
Geist / JetBrains Mono, no border-radius).

## Decision

- **React 18 + TypeScript 5 + Vite 5.** Type safety covers the API
  contract layer; Vite gives sub-second HMR and a simple production build.
- **react-router-dom v6** for routing. No SSR; this is a thick client
  for ops, not a marketing site.
- **No CSS framework.** Theme is hand-authored CSS custom properties in
  `src/styles/tokens.css`, a faithful translation of `design-system.md`.
  Components ship their own scoped CSS files via Vite's CSS modules.
- **Recharts** added in this release for the dashboard. Until then no chart
  library is bundled.
- **No state-management library.** React's local state plus a tiny
  `AuthContext` is sufficient for  React Query or SWR gets a
  re-evaluation in this release when more than one read endpoint per page
  appears.

## Alternatives considered

- **Next.js.** Brings SSR / app-router complexity for zero benefit when
  the API is a separate FastAPI service. Rejected.
- **SvelteKit.** Smaller community of WAF-related examples, fewer eyes
  on the supervisor's side. Rejected for project-grading reasons rather
  than technical ones.
- **Tailwind.** Produces verbose JSX, blurs the design-system intent
  ("один акцент на экран") and costs build-tool surface. Rejected.
- **shadcn/ui.** Tailwind-based; same objection as above.

## Consequences

- Bundle stays small (<60 KB JS gzipped target for the login + dashboard
  routes). Easy to inspect from the defence laptop.
- Each new page costs more boilerplate than a CSS framework would, but
  the CSS lives in one obvious file per component, which is easier to
  defend in person.
- We commit to writing TypeScript types for the API surface manually
  in this release. ADR-0004 ( candidate) covers automating this from
  the FastAPI OpenAPI export.

## Follow-ups

- ADR-0004 — Generate API types from OpenAPI .
- ADR-0005 — Persistent auth via HTTP-only cookies .
