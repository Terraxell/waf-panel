// MlThresholdSlider  (B10 close-out).
//
// WHY: this is the kill-switch surface from ADR-0011. A regression that
// silently disables the rollback button or the admin gate would leave
// operators unable to react to a misbehaving model. The tests here
// cover both the happy editor path and the read-only-for-non-admin path.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n";
import type { CurrentUser } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: {
    mlThresholdGet: vi.fn(),
    mlThresholdPut: vi.fn(),
  },
}));

import { api } from "@/lib/api";
import { MlThresholdSlider } from "./MlThresholdSlider";

const ADMIN: CurrentUser = {
  id: "1", email: "a@x", role: "admin", is_active: true,
};
const VIEWER: CurrentUser = {
  id: "2", email: "v@x", role: "viewer", is_active: true,
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

describe("<MlThresholdSlider>", () => {
  it("renders the read-only state for non-admin users", async () => {
    vi.mocked(api.mlThresholdGet).mockResolvedValue({ value: 0.85 });
    render(wrap(<MlThresholdSlider user={VIEWER} />));
    // Wait for the value to land.
    await screen.findByText("0.85");
    // Slider exists but is disabled (admin-only); no Apply / Rollback buttons.
    const slider = screen.getByRole("slider");
    expect(slider).toBeDisabled();
    expect(screen.queryByRole("button", { name: /apply/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /roll back/i })).toBeNull();
  });

  it("admin sees Apply + Rollback; Apply fires PUT with the new value", async () => {
    vi.mocked(api.mlThresholdGet).mockResolvedValue({ value: 0.9 });
    vi.mocked(api.mlThresholdPut).mockResolvedValue({ value: 0.5 });

    render(wrap(<MlThresholdSlider user={ADMIN} />));
    const slider = (await screen.findByRole("slider")) as HTMLInputElement;

    // Move the slider — onChange fires once per fireEvent.change.
    const user = userEvent.setup();
    await user.click(slider);
    // Use fireEvent through the input value setter — userEvent doesn't
    // expose a direct way to set a range value smoothly across browsers.
    slider.value = "0.5";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
    slider.dispatchEvent(new Event("change", { bubbles: true }));

    const apply = await screen.findByRole("button", { name: /apply/i });
    await waitFor(() => expect(apply).not.toBeDisabled());
    await user.click(apply);

    await waitFor(() => {
      expect(api.mlThresholdPut).toHaveBeenCalledWith(0.5);
    });
  });

  it("Rollback resets to 1.0 when block-mode is currently active", async () => {
    vi.mocked(api.mlThresholdGet).mockResolvedValue({ value: 0.7 });
    vi.mocked(api.mlThresholdPut).mockResolvedValue({ value: 1.0 });

    render(wrap(<MlThresholdSlider user={ADMIN} />));
    const rollback = await screen.findByRole("button", { name: /roll back/i });
    await waitFor(() => expect(rollback).not.toBeDisabled());

    await userEvent.setup().click(rollback);
    await waitFor(() => {
      expect(api.mlThresholdPut).toHaveBeenCalledWith(1.0);
    });
  });

  it("Rollback is disabled when threshold is already 1.0 (annotate-only)", async () => {
    vi.mocked(api.mlThresholdGet).mockResolvedValue({ value: 1.0 });
    render(wrap(<MlThresholdSlider user={ADMIN} />));
    const rollback = await screen.findByRole("button", { name: /roll back/i });
    expect(rollback).toBeDisabled();
  });

  it("shows the annotate-only hint at θ=1.0", async () => {
    vi.mocked(api.mlThresholdGet).mockResolvedValue({ value: 1.0 });
    render(wrap(<MlThresholdSlider user={ADMIN} />));
    // The English ml.threshold.off string contains the word "annotate".
    await screen.findByText(/annotate/i);
  });
});
