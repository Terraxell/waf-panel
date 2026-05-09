// Light/Dark theme provider — (audit C-list item 17a).
//
// WHY: the panel sees long sessions on a dark room (NOC). A reflective
// off-white background (#FAFAF7) is the right default for a project
// summary screenshot, but operators on shift want a low-light variant.
//
// Storage: `waf-panel:theme` in localStorage. Three values:
//   "light" — force light
//   "dark"  — force dark
//   "auto"  — follow `prefers-color-scheme` (default for fresh installs)
//
// Toggling sets `data-theme` on <html>; tokens.css overrides via
// `:root[data-theme="dark"]`. CSS-only is preferred over JS-driven
// styles because every component already reads tokens.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemeMode = "light" | "dark" | "auto";
export type ThemeApplied = "light" | "dark";

const STORAGE_KEY = "waf-panel:theme";
const VALID: readonly ThemeMode[] = ["light", "dark", "auto"];

interface ThemeCtx {
  mode: ThemeMode;        // user pref (auto = follow OS)
  applied: ThemeApplied;  // what's actually rendered right now
  setMode: (m: ThemeMode) => void;
}

const Ctx = createContext<ThemeCtx | null>(null);

function readStored(): ThemeMode {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v && (VALID as readonly string[]).includes(v)) return v as ThemeMode;
  } catch {
    // private mode / SSR — fall through
  }
  return "auto";
}

function osPrefersDark(): boolean {
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  } catch {
    return false;
  }
}

function resolve(mode: ThemeMode): ThemeApplied {
  if (mode === "auto") return osPrefersDark() ? "dark" : "light";
  return mode;
}

interface ProviderProps {
  children: ReactNode;
  /** Force a starting mode — useful for tests/storybook. */
  initialMode?: ThemeMode;
}

export function ThemeProvider({ children, initialMode }: ProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(
    () => initialMode ?? readStored(),
  );
  const [applied, setApplied] = useState<ThemeApplied>(() => resolve(mode));

  // Mirror the resolved theme onto <html data-theme="…"> so CSS picks
  // it up. We do NOT remove the attribute when switching to light —
  // setting `data-theme="light"` makes intent explicit and lets CSS
  // tools see the value during inspection.
  useEffect(() => {
    document.documentElement.dataset.theme = applied;
    return () => {
      // No cleanup — leaving the last-set theme on the html element
      // matches what most prefers-color-scheme implementations do.
    };
  }, [applied]);

  // React to OS-level changes when in "auto" mode.
  useEffect(() => {
    if (mode !== "auto") {
      setApplied(mode);
      return;
    }
    setApplied(osPrefersDark() ? "dark" : "light");
    let mql: MediaQueryList | null = null;
    try {
      mql = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      return; // jsdom in some configs has no matchMedia
    }
    const handler = (e: MediaQueryListEvent) => {
      setApplied(e.matches ? "dark" : "light");
    };
    // addEventListener is the modern API; older Safari uses addListener.
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", handler);
      return () => mql?.removeEventListener("change", handler);
    } else if (typeof mql.addListener === "function") {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (mql as any).addListener(handler);
      return () => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (mql as any).removeListener(handler);
      };
    }
  }, [mode]);

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m);
    try {
      window.localStorage.setItem(STORAGE_KEY, m);
    } catch {
      // private mode — best-effort
    }
  }, []);

  const value = useMemo<ThemeCtx>(
    () => ({ mode, applied, setMode }),
    [mode, applied, setMode],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const v = useContext(Ctx);
  if (!v) {
    throw new Error("useTheme must be used inside <ThemeProvider>");
  }
  return v;
}
