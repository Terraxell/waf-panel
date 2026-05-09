// Lightweight i18n — Sprint 12 hotfix.
//
// WHY: the project's frontend is small and fully typed. Pulling react-i18next
// would bloat the bundle. We need: four locales (RU, EN, DE, FR), a
// switcher in the shell, one helper hook in components.
//
// Persistence:
//   * On boot, read `localStorage.lang` if present.
//   * Otherwise honour `navigator.language` — first two chars decide:
//       ru-* → ru, de-* → de, fr-* → fr, anything else → en.
//   * Toggle from LanguageSwitcher writes back to localStorage.
//
// Adding a string: add to en.ts (source of truth) and the three sibling
// dicts. TypeScript via the `Locale` type fails the build if any side
// is missing a key.
//
// Adding a language: add the code to `Lang`, append a dict to `DICTS`,
// extend `detectInitialLang()` to recognise the browser tag, and add a
// button in `LanguageSwitcher`.

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { de } from "./locales/de";
import { en, type EnDict } from "./locales/en";
import { fr } from "./locales/fr";
import { ru } from "./locales/ru";

export type Lang = "ru" | "en" | "de" | "fr";

// WHY: the source-of-truth shape is whatever EN ships — `EnDict` maps
// every EN key to `string`. Sibling dicts (RU/DE/FR) are typed against
// the same shape, so a missing or extra key on either side is a
// build-time error, but values are free strings (not English literals).
type LocaleShape = EnDict;

const DICTS: Record<Lang, LocaleShape> = { en, ru, de, fr };

interface I18nContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: keyof LocaleShape, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

const STORAGE_KEY = "waf-panel:lang";

function detectInitialLang(): Lang {
  // SAFETY: SSR / pre-hydration / disabled storage → fall through cleanly.
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "ru" || saved === "en" || saved === "de" || saved === "fr") {
      return saved;
    }
  } catch {
    /* localStorage unavailable */
  }
  if (typeof navigator !== "undefined" && navigator.language) {
    const tag = navigator.language.toLowerCase();
    if (tag.startsWith("ru")) return "ru";
    if (tag.startsWith("de")) return "de";
    if (tag.startsWith("fr")) return "fr";
  }
  return "en";
}

interface I18nProviderProps {
  children: ReactNode;
  /** Override for tests — bypasses localStorage / navigator detection. */
  initialLang?: Lang;
}

export function I18nProvider({ children, initialLang }: I18nProviderProps) {
  const [lang, setLangState] = useState<Lang>(() => initialLang ?? detectInitialLang());

  // WHY: keep <html lang="..."> in sync so screen-readers and search engines
  // get the right locale. One DOM attribute, one effect — no library needed.
  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = lang;
    }
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* localStorage unavailable; skip persistence, runtime still works */
    }
  }, []);

  const t = useCallback(
    (key: keyof LocaleShape, vars?: Record<string, string | number>) => {
      // WHY: never throw on a missing key — show the raw key rather than
      // crash. Tests catch missing keys at build time via the `LocaleShape`
      // constraint above.
      const dict = DICTS[lang];
      const fallback = DICTS.en;
      const raw = (dict[key] ?? fallback[key] ?? key) as string;
      if (!vars) return raw;
      return raw.replace(/\{(\w+)\}/g, (_, name) =>
        name in vars ? String(vars[name]) : `{${name}}`,
      );
    },
    [lang],
  );

  const value = useMemo<I18nContextValue>(() => ({ lang, setLang, t }), [lang, setLang, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n() must be called inside <I18nProvider>");
  }
  return ctx;
}

/** Convenience hook — most components only need `t`. */
export function useT() {
  return useI18n().t;
}
