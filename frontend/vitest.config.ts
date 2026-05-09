// vitest.config.ts
//
// WHY: keep test config separate from vite.config.ts so the production
// bundler doesn't drag in test-only globals. `vitest` reads this when
// `npm run test` runs; `vite` and `vite build` ignore it.

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // WHY: ignore node_modules + the built-in Vite-shipped fixtures; only
    // pick up our hand-written tests under src/.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    // WHY no a11y.test.tsx exclude here: vitest applies the config
    // exclude even when a path is passed on the CLI, so excluding the
    // a11y test in this file would also break the dedicated
    // `npm run test:a11y` invocation. Instead, the main `npm run test`
    // script passes --exclude on the CLI; the a11y script doesn't.
  },
});
