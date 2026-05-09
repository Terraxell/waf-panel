// Skeleton — light visual unit. Just covers the props contract:
// single line, multi-line group, last-line tapered width.

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Skeleton } from "./Skeleton";

describe("<Skeleton>", () => {
  it("renders a single shimmer block by default", () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelectorAll(".skeleton")).toHaveLength(1);
    expect(container.querySelector(".skeleton__group")).toBeNull();
  });

  it("renders N lines when lines > 1", () => {
    const { container } = render(<Skeleton lines={4} />);
    expect(container.querySelectorAll(".skeleton")).toHaveLength(4);
  });

  it("respects width / height props", () => {
    const { container } = render(<Skeleton height="3rem" width="80%" />);
    const node = container.querySelector(".skeleton") as HTMLElement;
    expect(node.style.height).toBe("3rem");
    expect(node.style.width).toBe("80%");
  });

  it("tapers the last line of a multi-line group", () => {
    const { container } = render(<Skeleton lines={3} />);
    const lines = container.querySelectorAll(".skeleton");
    // First two lines: 100% width default; last: 60% (so the eye perceives
    // a paragraph end). The CSS reads the inline style.
    expect((lines[2] as HTMLElement).style.width).toBe("60%");
  });

  it("is aria-hidden so screen-readers ignore loading visuals", () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelector(".skeleton")).toHaveAttribute("aria-hidden", "true");
  });
});
