import { ButtonHTMLAttributes, forwardRef } from "react";
import "./Button.css";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = "primary", loading, disabled, className, children, ...rest },
  ref,
) {
  // WHY: the design system mandates a single accent per screen, so we keep
  //      the variants narrow on purpose.
  return (
    <button
      ref={ref}
      data-variant={variant}
      disabled={disabled || loading}
      className={`btn ${className ?? ""}`}
      {...rest}
    >
      {loading ? "…" : children}
    </button>
  );
});
