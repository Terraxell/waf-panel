import "./Skeleton.css";

interface Props {
  /** Cosmetic — px or any CSS length. Defaults to "1rem" line height. */
  height?: string;
  /** Cosmetic — defaults to 100% (block). */
  width?: string;
  /** How many shimmer lines to render — useful for table-rows / list items. */
  lines?: number;
}

/**
 * Loading skeleton — replaces "Загружается…" text. CSS-only animation
 * (no extra deps), respects `prefers-reduced-motion`. Sticks to the
 * design system's neutral muted-foreground colour for the shimmer
 * highlight so it doesn't compete visually with real content.
 */
export function Skeleton({ height = "1rem", width = "100%", lines = 1 }: Props) {
  if (lines === 1) {
    return <div className="skeleton" style={{ height, width }} aria-hidden="true" />;
  }
  return (
    <div className="skeleton__group" aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{ height, width: i === lines - 1 ? "60%" : width }}
        />
      ))}
    </div>
  );
}
