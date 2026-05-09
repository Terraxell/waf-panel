// Theme provider — (audit C17a).
//
// WHY: the provider has three moving parts that all silently degrade
// to the wrong appearance if they break:
//   1. Mode resolution: "auto" must follow `prefers-color-scheme`.
//   2. Persistence: localStorage round-trips three valid values.
//   3. <html data-theme> reflection: every subsequent mount on the
//      same page sees the right CSS variables.

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider, useTheme, type ThemeMode } from "./theme";

function ThemeProbe() {
  const { mode, applied } = useTheme();
  return (
    <span data-testid="probe">
      {mode}/{applied}
    </span>
  );
}

function ToggleButton() {
  const { mode, setMode } = useTheme();
  const next: ThemeMode = mode === "dark" ? "light" : "dark";
  return (
    <button onClick={() => setMode(next)} aria-label="set">{next}</button>
  );
}

function mockMatchMedia(matches: boolean) {
  const handlers = new Set<(e: MediaQueryListEvent) => void>();
  const mql: Partial<MediaQueryList> & {
    fire: (m: boolean) => void;
  } = {
    matches,
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_evt: string, cb: EventListener) => {
      handlers.add(cb as (e: MediaQueryListEvent) => void);
    },
    removeEventListener: (_evt: string, cb: EventListener) => {
      handlers.delete(cb as (e: MediaQueryListEvent) => void);
    },
    fire: (m: boolean) => {
      for (const h of handlers) h({ matches: m } as MediaQueryListEvent);
    },
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).matchMedia = vi.fn().mockReturnValue(mql);
  return mql;
}

beforeEach(() => {
  window.localStorage.clear();
  // Default: OS prefers light.
  mockMatchMedia(false);
  delete (document.documentElement.dataset as Record<string, string | undefined>).theme;
});

afterEach(() => vi.restoreAllMocks());

describe("<ThemeProvider> — initial mode resolution", () => {
  it("defaults to auto + light when no storage and OS prefers light", () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("auto/light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("defaults to auto + dark when OS prefers dark", () => {
    mockMatchMedia(true);
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("auto/dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("respects an explicit value in localStorage", () => {
    window.localStorage.setItem("waf-panel:theme", "dark");
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("dark/dark");
  });

  it("ignores garbage in localStorage and falls through to auto", () => {
    window.localStorage.setItem("waf-panel:theme", "neon-rainbow");
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("auto/light");
  });

  it("uses initialMode prop when given (test/storybook hook)", () => {
    render(
      <ThemeProvider initialMode="dark">
        <ThemeProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("dark/dark");
  });
});

describe("<ThemeProvider> — persistence + DOM reflection", () => {
  it("persists setMode to localStorage and updates <html data-theme>", async () => {
    render(
      <ThemeProvider initialMode="light">
        <ThemeProbe />
        <ToggleButton />
      </ThemeProvider>,
    );
    expect(document.documentElement.dataset.theme).toBe("light");
    await userEvent.setup().click(screen.getByLabelText("set"));
    expect(window.localStorage.getItem("waf-panel:theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("auto mode reacts to OS prefers-color-scheme changes", () => {
    const mql = mockMatchMedia(false);
    render(
      <ThemeProvider initialMode="auto">
        <ThemeProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("auto/light");
    act(() => mql.fire(true));
    expect(screen.getByTestId("probe")).toHaveTextContent("auto/dark");
  });
});
