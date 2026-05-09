// MlBadge — Sprint 13 (audit B10 close-out + C17b refactor).
//
// WHY: this badge is the user's only window into the ML verdict. It
// MUST handle three states cleanly: prob present, fallback (ml-service
// down), and `enabled=false`. Sprint 13 moved the explanation into a
// Popover (keyboard-accessible, no native title= delay), so we no
// longer assert against the title attribute.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n";
import type { MlInspectRequest, MlInspectResponse, MlExplainResponse } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: {
    mlInspect: vi.fn(),
    mlExplain: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { MlBadge } from "./MlBadge";

const REQ: MlInspectRequest = {
  method: "GET",
  path: "/login",
  query: "id=1",
  user_agent: "curl/8",
};

function wrap(children: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return (
    <I18nProvider initialLang="en">
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </I18nProvider>
  );
}

afterEach(() => vi.clearAllMocks());

describe("<MlBadge>", () => {
  it("renders nothing when enabled=false", () => {
    const { container } = render(wrap(<MlBadge request={REQ} enabled={false} />));
    expect(container.querySelector(".ml-badge")).toBeNull();
    expect(api.mlInspect).not.toHaveBeenCalled();
  });

  it("shows the probability rounded to 2 decimals when ml-service responds", async () => {
    const inspectResp: MlInspectResponse = {
      prob: 0.873,
      fallback: false,
      fallback_reason: null,
      cached: false,
      model: "v20260601",
      model_version: "v20260601",
      latency_ms: 4,
    };
    const explainResp: MlExplainResponse = {
      prob: 0.873,
      contributors: [{ feature: "tok_union_select", weight: 0.42 }],
      model: "v20260601",
      model_version: "v20260601",
      method: "feature_importances",
      fallback_reason: null,
    };
    vi.mocked(api.mlInspect).mockResolvedValue(inspectResp);
    vi.mocked(api.mlExplain).mockResolvedValue(explainResp);

    render(wrap(<MlBadge request={REQ} />));
    const badge = await screen.findByText("0.87");
    expect(badge).toHaveClass("ml-badge--high");
  });

  it("falls back to em-dash when ml-service is unavailable", async () => {
    vi.mocked(api.mlInspect).mockResolvedValue({
      prob: null,
      fallback: true,
      fallback_reason: "network",
      cached: false,
      model: null,
      model_version: null,
      latency_ms: 0,
    });
    render(wrap(<MlBadge request={REQ} />));
    const dash = await screen.findByText("—");
    expect(dash).toHaveAttribute("data-fallback", "true");
    // /explain is gated on a present prob — no second call.
    await waitFor(() => {
      expect(api.mlExplain).not.toHaveBeenCalled();
    });
  });

  it("classifies low/med/high by probability bands", async () => {
    vi.mocked(api.mlInspect).mockResolvedValue({
      prob: 0.12,
      fallback: false,
      fallback_reason: null,
      cached: true,
      model: "vX",
      model_version: "vX",
      latency_ms: 1,
    });
    vi.mocked(api.mlExplain).mockResolvedValue({
      prob: 0.12,
      contributors: [],
      model: "vX",
      model_version: "vX",
      method: "feature_importances",
      fallback_reason: null,
    });
    render(wrap(<MlBadge request={REQ} />));
    const badge = await screen.findByText("0.12");
    expect(badge).toHaveClass("ml-badge--low");
  });

  it("opens a popover with prob + model on hover", async () => {
    vi.mocked(api.mlInspect).mockResolvedValue({
      prob: 0.55,
      fallback: false,
      fallback_reason: null,
      cached: true,
      model: "v20260601",
      model_version: "v20260601",
      latency_ms: 1,
    });
    vi.mocked(api.mlExplain).mockResolvedValue({
      prob: 0.55,
      contributors: [{ feature: "len_query", weight: -0.1 }],
      model: "v20260601",
      model_version: "v20260601",
      method: "feature_importances",
      fallback_reason: null,
    });
    render(wrap(<MlBadge request={REQ} />));
    const badge = await screen.findByText("0.55");
    await userEvent.setup().hover(badge);
    // role="tooltip" panel becomes visible — assert the model name and
    // the contributor feature both rendered as text inside it.
    const panel = await screen.findByRole("tooltip");
    expect(panel.textContent).toContain("v20260601");
    expect(panel.textContent).toContain("len_query");
  });

  it("popover surfaces the fallback reason instead of a probability", async () => {
    vi.mocked(api.mlInspect).mockResolvedValue({
      prob: null,
      fallback: true,
      fallback_reason: "timeout",
      cached: false,
      model: null,
      model_version: null,
      latency_ms: 5,
    });
    render(wrap(<MlBadge request={REQ} />));
    const badge = await screen.findByText("—");
    await userEvent.setup().hover(badge);
    const panel = await screen.findByRole("tooltip");
    // English locale ml.badge.unavailable: "ML unavailable: {reason}"
    expect(panel.textContent?.toLowerCase()).toContain("unavailable");
    expect(panel.textContent).toContain("timeout");
  });
});
