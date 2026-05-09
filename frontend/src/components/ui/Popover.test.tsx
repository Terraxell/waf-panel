// Popover — Sprint 13 (audit C17b).
//
// WHY: every claim the comment in Popover.tsx makes about
// keyboard-parity, role="tooltip", and Esc-dismiss should fail loud
// if a future refactor breaks it.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Popover } from "./Popover";

afterEach(() => vi.restoreAllMocks());

describe("<Popover>", () => {
  it("does not render the panel until trigger is interacted with", () => {
    render(
      <Popover content={<span>secret</span>}>
        <span data-testid="t">badge</span>
      </Popover>,
    );
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("opens on mouse hover and closes on mouseleave", async () => {
    render(
      <Popover content={<span>panel-body</span>}>
        <span data-testid="t">badge</span>
      </Popover>,
    );
    const trigger = screen.getByTestId("t");
    const user = userEvent.setup();
    await user.hover(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("panel-body");
    await user.unhover(trigger);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("opens on focus (keyboard parity) and dismisses on Escape", async () => {
    render(
      <Popover content={<span>k</span>}>
        <span data-testid="t">trig</span>
      </Popover>,
    );
    const trigger = screen.getByTestId("t");
    // Trigger gets tabIndex={0} from the Popover so focus() works.
    trigger.focus();
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    await userEvent.setup().keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("links trigger to panel via aria-describedby when open", async () => {
    render(
      <Popover content={<span>x</span>}>
        <span data-testid="t">trig</span>
      </Popover>,
    );
    const trigger = screen.getByTestId("t");
    await userEvent.setup().hover(trigger);
    const panel = screen.getByRole("tooltip");
    expect(trigger).toHaveAttribute("aria-describedby", panel.id);
  });

  it("makes a non-focusable trigger focusable via tabIndex=0", () => {
    render(
      <Popover content="x">
        <span data-testid="t">trig</span>
      </Popover>,
    );
    expect(screen.getByTestId("t")).toHaveAttribute("tabindex", "0");
  });
});
