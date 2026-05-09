// Vitest global setup .
//
// WHY: `@testing-library/jest-dom` registers DOM matchers (e.g.
// `toBeInTheDocument`, `toHaveAttribute`). Doing it in setupFiles means
// individual tests don't have to import it, and the global TS types
// surface in every spec file.

import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  // Each test renders into its own DOM root; cleanup avoids leaks
  // between tests in the same file.
  cleanup();
});
