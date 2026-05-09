import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { MlInspectRequest } from "@/lib/types";
import { Popover } from "./Popover";
import "./MlBadge.css";

interface MlBadgeProps {
  /** Same shape the /api/v1/ml/inspect endpoint expects. */
  request: MlInspectRequest;
  /** When false, the component renders nothing — useful for opt-out rows. */
  enabled?: boolean;
}

/**
 * Small inline widget shown in the Incidents table. Calls /ml/inspect for
 * the probability and /ml/explain for the top-3 contributors. Both endpoints
 * fail open server-side, so the worst case is a `—` chip and a popover
 * explaining why ML couldn't decide.
 *
 * Sprint 13 (audit C17b): the explanation moved out of `title=` into a
 * proper Popover — keyboard-accessible, instantly visible, and with the
 * contributors stack rendered as separate rows rather than ASCII soup.
 */
export function MlBadge({ request, enabled = true }: MlBadgeProps) {
  const t = useT();
  const inspect = useQuery({
    queryKey: ["ml-inspect", request],
    queryFn: () => api.mlInspect(request),
    enabled,
    staleTime: 30_000,
  });

  const explain = useQuery({
    queryKey: ["ml-explain", request],
    queryFn: () => api.mlExplain(request, 3),
    // Don't ask for an explanation when there's nothing to explain.
    enabled: enabled && inspect.data?.prob != null,
    staleTime: 30_000,
  });

  if (!enabled) return null;

  if (inspect.isLoading) {
    return <span className="ml-badge ml-badge--loading mono-label">…</span>;
  }

  const data = inspect.data;
  const fallback = !data || data.fallback || data.prob == null;
  const prob = data?.prob ?? null;

  let level: "high" | "med" | "low" | "na" = "na";
  if (prob != null) {
    level = prob >= 0.8 ? "high" : prob >= 0.4 ? "med" : "low";
  }

  // Popover body — structured rows instead of `\n` joined strings.
  const body = fallback ? (
    <span className="ml-badge__popover-row">
      {t("ml.badge.unavailable", {
        reason: data?.fallback_reason ?? t("ml.badge.no_response"),
      })}
    </span>
  ) : (
    <>
      <span className="ml-badge__popover-row">
        {t("ml.badge.prob", { value: (prob ?? 0).toFixed(3) })}
      </span>
      {data?.model && (
        <span className="ml-badge__popover-row">
          {t("ml.badge.model", { name: data.model })}
        </span>
      )}
      {data?.cached && (
        <span className="ml-badge__popover-row">{t("ml.badge.cache_hit")}</span>
      )}
      {explain.data?.contributors?.length ? (
        <>
          <span className="ml-badge__popover-row ml-badge__popover-row--header">
            {t("ml.badge.contributors")}
          </span>
          {explain.data.contributors.map((c) => (
            <span
              key={c.feature}
              className={`ml-badge__contrib ml-badge__contrib--${
                c.weight >= 0 ? "pos" : "neg"
              }`}
            >
              <code className="ml-badge__contrib-weight">
                {c.weight >= 0 ? "+" : "−"}
                {Math.abs(c.weight).toFixed(2)}
              </code>
              <code className="ml-badge__contrib-name">{c.feature}</code>
            </span>
          ))}
        </>
      ) : null}
    </>
  );

  return (
    <Popover content={body}>
      <span
        className={`ml-badge ml-badge--${level}`}
        data-fallback={fallback || undefined}
      >
        {fallback ? "—" : (prob ?? 0).toFixed(2)}
      </span>
    </Popover>
  );
}
