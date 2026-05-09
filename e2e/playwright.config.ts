// Playwright config for the waf-panel smoke suite.
//
// WHY a separate package: Playwright wants its own node_modules + a
// chromium download. Co-locating it with frontend/ would make a one-
// off CI install drag in vitest, vite, etc., and a frontend dev who
// just wants `npm test` would pull a 250 MB chromium. e2e/ pays its
// own cost, owned by its own CI job.

import { defineConfig, devices } from "@playwright/test";

const PANEL_URL = process.env.E2E_PANEL_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./tests",
  // WHY a 30 s default: docker compose containers take ~5 s to warm up
  // even after the healthcheck flips green; the bootstrap probe in App.tsx
  // adds another second. 30 s catches a slow CI runner.
  timeout: 30_000,
  expect: { timeout: 10_000 },
  // CI = one worker (deterministic ordering, easier debugging on a flake);
  // local = parallel.
  fullyParallel: !process.env.CI,
  workers: process.env.CI ? 1 : undefined,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: PANEL_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    // SAFETY: ignoreHTTPSErrors=false on purpose -- if the demo deploy
    // serves a broken cert, the test should fail loudly.
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
