import { useI18n, type Lang } from "@/lib/i18n";
import "./LanguageSwitcher.css";

const LANGS: { value: Lang; label: string }[] = [
  { value: "ru", label: "RU" },
  { value: "en", label: "EN" },
  { value: "de", label: "DE" },
  { value: "fr", label: "FR" },
];

/**
 * Four-button toggle in the shell header — RU / EN / DE / FR.
 *
 * WHY: a `<select>` would be one widget, but the panel's design system
 * has no native form controls beyond Input/Button (radius=0, monospace
 * label semantics). A row of buttons matches the segmented filters
 * elsewhere (1H / 24H / 7D in Incidents).
 */
export function LanguageSwitcher() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="lang-switch" role="group" aria-label={t("shell.lang_label")}>
      {LANGS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`lang-switch__btn${opt.value === lang ? " lang-switch__btn--active" : ""}`}
          onClick={() => setLang(opt.value)}
          aria-pressed={opt.value === lang}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
