// Runtime accessibility smoke test — task #127.
//
// WHY: a static lint catches obvious mistakes (alt-text, htmlFor) but
// not the runtime stuff axe checks: ARIA roles consistency, focusable
// element ordering, contrast (when computed). vitest-axe + axe-core
// renders a component into jsdom and runs the same engine the
// Chrome DevTools Lighthouse a11y panel uses.
//
// Scope: the isolated UI primitives + the Login page. Pages that
// depend on React Router / React Query / cookie auth are out of
// scope here; they are covered by the static jsx-a11y lint pass.

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { axe } from "vitest-axe";
import * as axeMatchers from "vitest-axe/matchers";
import { MemoryRouter } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Login } from "@/pages/Login";
import { I18nProvider } from "@/lib/i18n";

// vitest-axe ships matchers under /matchers; calling expect.extend
// brings `toHaveNoViolations` onto the vitest assertion chain.
expect.extend(axeMatchers);

describe("a11y smoke (#127)", () => {
  it("Button has no axe violations", async () => {
    const { container } = render(<Button>Click me</Button>);
    const results = await axe(container);
    // toHaveNoViolations comes from the matchers we just extended.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(results as any).toHaveNoViolations();
  });

  it("Input with a label has no axe violations", async () => {
    const { container } = render(
      <Input label="Email" type="email" defaultValue="" onChange={() => {}} />,
    );
    const results = await axe(container);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(results as any).toHaveNoViolations();
  });

  it("Card with title and content has no axe violations", async () => {
    const { container } = render(
      <Card title="Requests" hint="last 24 h">
        <strong>1 234</strong>
      </Card>,
    );
    const results = await axe(container);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(results as any).toHaveNoViolations();
  });

  it("Login page has no axe violations", async () => {
    const { container } = render(
      <I18nProvider>
        <MemoryRouter>
          <Login />
        </MemoryRouter>
      </I18nProvider>,
    );
    const results = await axe(container);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(results as any).toHaveNoViolations();
  });
});
