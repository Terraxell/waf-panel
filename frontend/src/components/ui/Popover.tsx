// Popover — Sprint 13 (audit C17b).
//
// WHY: native `title=` has three problems for the MlBadge surface:
//   1. Delay before show (~700 ms on most browsers) makes the badge
//      feel unresponsive when an analyst is scanning rows.
//   2. Cannot be opened with the keyboard (focus alone doesn't trip it).
//   3. Cannot be styled — line breaks render but indentation does not,
//      and contributors with `+` / `−` weights look like ASCII soup.
//
// This Popover:
//   - shows on hover **and** on focus (keyboard parity).
//   - dismisses on blur, on `Esc`, and on `mouseleave`.
//   - uses `role="tooltip"` + `aria-describedby` so screen readers
//     announce the content alongside the trigger label.
//   - has no positioning library (single fixed offset above the
//     trigger) and no portal (avoids z-index pile-ups for now).

import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import "./Popover.css";

interface PopoverProps {
  /** Rich tooltip body. Plain strings, fragments, or any JSX. */
  content: ReactNode;
  /** The element that opens the popover on hover/focus. */
  children: ReactElement;
  /** Optional className appended to the popover panel. */
  className?: string;
}

export function Popover({ content, children, className }: PopoverProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);

  const close = useCallback(() => setOpen(false), []);
  const show = useCallback(() => setOpen(true), []);

  // Esc dismisses the popover even when focus is somewhere inside the
  // trigger's subtree (e.g. a child <button>).
  useEffect(() => {
    if (!open) return;
    const onDocKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onDocKey);
    return () => document.removeEventListener("keydown", onDocKey);
  }, [open]);

  // Click outside dismisses; useful when the trigger took focus and the
  // user wants to move on without keyboard interaction.
  useEffect(() => {
    if (!open) return;
    const onDocPointer = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocPointer);
    return () => document.removeEventListener("mousedown", onDocPointer);
  }, [open]);

  // We clone the trigger to attach focus / blur handlers without
  // forcing the caller to use a specific element type. `aria-describedby`
  // links the trigger to the panel for screen readers.
  if (!isValidElement(children)) {
    // Defensive: render content inline rather than crashing.
    return <>{children}{content}</>;
  }

  const triggerProps = (children.props ?? {}) as Record<string, unknown>;
  const trigger = cloneElement(children as ReactElement<Record<string, unknown>>, {
    "aria-describedby": open ? id : undefined,
    onFocus: (e: React.FocusEvent) => {
      show();
      const orig = triggerProps.onFocus as ((ev: React.FocusEvent) => void) | undefined;
      orig?.(e);
    },
    onBlur: (e: React.FocusEvent) => {
      // Only close on real blur, not on focus bouncing within the wrap.
      if (!wrapRef.current?.contains(e.relatedTarget as Node)) close();
      const orig = triggerProps.onBlur as ((ev: React.FocusEvent) => void) | undefined;
      orig?.(e);
    },
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      const orig = triggerProps.onKeyDown as ((ev: KeyboardEvent) => void) | undefined;
      orig?.(e);
    },
    // Make the trigger keyboard-reachable when the caller hands us an
    // element that isn't natively focusable (e.g. <span>). If the
    // caller already set tabIndex, keep theirs.
    tabIndex: triggerProps.tabIndex ?? 0,
  });

  return (
    <span
      ref={wrapRef}
      className="popover"
      onMouseEnter={show}
      onMouseLeave={close}
    >
      {trigger}
      {open && (
        <span
          id={id}
          role="tooltip"
          className={`popover__panel${className ? ` ${className}` : ""}`}
        >
          {content}
        </span>
      )}
    </span>
  );
}
