import { useTheme, type ThemeMode } from "@/lib/theme";
import { useT } from "@/lib/i18n";
import "./ThemeToggle.css";

const MODES: { value: ThemeMode; key: "shell.theme.light" | "shell.theme.dark" | "shell.theme.auto" }[] = [
  { value: "light", key: "shell.theme.light" },
  { value: "auto",  key: "shell.theme.auto"  },
  { value: "dark",  key: "shell.theme.dark"  },
];

/**
 * Three-state theme switcher in the shell header.
 *
 * WHY three states (and not a single toggle):
 *   - "auto" defers to OS prefs — the right default for first-time
 *     users in a dark OS.
 *   - "light"/"dark" are explicit overrides — operator preference can
 *     differ from the workstation's OS theme.
 *
 * Rendered as a segmented button group (matches LanguageSwitcher) so
 * the affordance "this is a discrete pick of one of N" is consistent.
 */
export function ThemeToggle() {
  const { mode, setMode } = useTheme();
  const t = useT();
  return (
    <div className="theme-toggle" role="group" aria-label={t("shell.theme.label")}>
      {MODES.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`theme-toggle__btn${opt.value === mode ? " theme-toggle__btn--active" : ""}`}
          onClick={() => setMode(opt.value)}
          aria-pressed={opt.value === mode}
        >
          {t(opt.key)}
        </button>
      ))}
    </div>
  );
}
