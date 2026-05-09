# e2e — Playwright smoke tests

Drives a real Chromium against a running stack and walks through the
most-used flows.

## Run locally

```bash
# 1. Bring the stack up.
make up
make bootstrap   # alembic + admin seed

# 2. Install Playwright + chromium (one-off, ~250 MB).
cd e2e
npm install
npm run install-browsers

# 3. Run.
npm test                 # headless
npm run test:headed      # see the browser
```

## Environment

| Var                   | Default                  | Notes                                     |
|-----------------------|--------------------------|-------------------------------------------|
| `E2E_PANEL_URL`       | `http://localhost:3000`  | Where the SPA serves                      |
| `E2E_ADMIN_PASSWORD`  | `admin`                  | Override after rotation                   |
| `CI`                  | unset                    | Setting it serializes workers + GitHub reporter |

## What's covered

- `smoke.spec.ts::happy-path` — anonymous → login → dashboard →
  rules → audit → logout. The thinking: if any of those routes 500's
  or the auth flow breaks, this test catches it before a tag.
- `smoke.spec.ts::live-status pill` — confirms the `.dashboard__live`
  pill from #122 actually renders in the DOM.

## What's NOT covered

- Cross-browser parity (only chromium configured). Add Firefox /
  WebKit projects in `playwright.config.ts` if a recruiter cares.
- Visual regression. Could add `await expect(page).toHaveScreenshot()`
  but that needs golden images and a stable rendering target.
- Mutating flows that race with the audit log (rule create / user
  create). Punted; tested at the unit + vitest level instead.
