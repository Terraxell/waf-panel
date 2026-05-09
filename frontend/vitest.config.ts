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
    // WHY exclude: a11y.test.tsx is run by a separate `npm run test:a11y`
    // step in the dedicated CI a11y job (#127) so the main vitest pass
    // doesn't pull in vitest-axe / axe-core when those deps may not be
    // installed yet on a stripped-down dev clone.
    exclude: ["**/node_modules/**", "src/test/a11y.test.tsx"],
  },
});
