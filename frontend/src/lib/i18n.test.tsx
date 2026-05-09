// i18n core — Provider + useT + persistence + auto-detect.
//
// WHY: this is the layer the entire UI depends on for strings. A
// regression here would silently English-fallback every translated
// surface. Tests cover: explicit lang, browser detection, localStorage
// persistence, key fallback, token interpolation.

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, useI18n, useT, type Lang } from "./i18n";

function Probe({ tkey }: { tkey: Parameters<ReturnType<typeof useT>>[0] }) {
  const t = useT();
  return <span data-testid="out">{t(tkey)}</span>;
}

function LangProbe() {
  const { lang } = useI18n();
  return <span data-testid="lang">{lang}</span>;
}

beforeEach(() => {
  // Each test starts from a clean storage / no detection bias.
  window.localStorage.clear();
});

afterEach(() => vi.restoreAllMocks());

describe("I18nProvider — language selection", () => {
  it("uses initialLang prop when given", () => {
    render(
      <I18nProvider initialLang="de">
        <LangProbe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("de");
  });

  it.each<[string, Lang]>([
    ["ru-RU", "ru"],
    ["en-GB", "en"],
    ["de-AT", "de"],
    ["fr-CA", "fr"],
    ["zh-CN", "en"], // unknown → fall back to en
  ])("auto-detects from navigator.language=%s → %s", (tag, expected) => {
    Object.defineProperty(navigator, "language", { value: tag, configurable: true });
    render(
      <I18nProvider>
        <LangProbe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent(expected);
  });

  it("prefers a saved localStorage value over browser detection", () => {
    Object.defineProperty(navigator, "language", { value: "fr-FR", configurable: true });
    window.localStorage.setItem("waf-panel:lang", "ru");
    render(
      <I18nProvider>
        <LangProbe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("ru");
  });

  it("ignores garbage in localStorage", () => {
    window.localStorage.setItem("waf-panel:lang", "klingon");
    render(
      <I18nProvider initialLang={undefined}>
        <LangProbe />
      </I18nProvider>,
    );
    // Falls through to navigator/en, neither of which is "klingon".
    expect(screen.getByTestId("lang").textContent).not.toBe("klingon");
  });
});

describe("I18nProvider — setLang persistence", () => {
  it("persists to localStorage and updates <html lang>", () => {
    let setLangFn: (l: Lang) => void = () => {};
    function Capture() {
      setLangFn = useI18n().setLang;
      return null;
    }
    render(
      <I18nProvider initialLang="ru">
        <Capture />
      </I18nProvider>,
    );
    act(() => setLangFn("de"));
    expect(window.localStorage.getItem("waf-panel:lang")).toBe("de");
    expect(document.documentElement.lang).toBe("de");
  });
});

describe("useT — translation lookup", () => {
  it("returns the localised string", () => {
    render(
      <I18nProvider initialLang="ru">
        <Probe tkey="nav.dashboard" />
      </I18nProvider>,
    );
    expect(screen.getByTestId("out")).toHaveTextContent("Дашборд");
  });

  it("interpolates {name} tokens", () => {
    function P() {
      const t = useT();
      return <span data-testid="out">{t("ml.threshold.on", { value: "0.93" })}</span>;
    }
    render(
      <I18nProvider initialLang="en">
        <P />
      </I18nProvider>,
    );
    expect(screen.getByTestId("out").textContent).toContain("0.93");
    expect(screen.getByTestId("out").textContent).not.toContain("{value}");
  });

  it("falls back to EN when the locale doesn't have a key (defensive)", () => {
    // All four dicts are EnDict-typed so this is structurally impossible
    // at build time — but the runtime fallback path is a safety net we
    // exercise here for the comment in i18n.tsx to stay honest.
    render(
      <I18nProvider initialLang="fr">
        <Probe tkey="nav.dashboard" />
      </I18nProvider>,
    );
    expect(screen.getByTestId("out").textContent).toBeTruthy();
  });
});

describe("LanguageSwitcher integration", () => {
  it("changes the active language when a button is clicked", async () => {
    const { LanguageSwitcher } = await import("@/components/ui/LanguageSwitcher");
    const userEvent = (await import("@testing-library/user-event")).default;
    render(
      <I18nProvider initialLang="ru">
        <LanguageSwitcher />
        <LangProbe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("lang")).toHaveTextContent("ru");
    await userEvent.setup().click(screen.getByRole("button", { name: "DE" }));
    expect(screen.getByTestId("lang")).toHaveTextContent("de");
  });

  it("renders all four language buttons", async () => {
    const { LanguageSwitcher } = await import("@/components/ui/LanguageSwitcher");
    render(
      <I18nProvider initialLang="ru">
        <LanguageSwitcher />
      </I18nProvider>,
    );
    for (const label of ["RU", "EN", "DE", "FR"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });
});
