import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { CurrentUser } from "@/lib/types";
import "./MlThresholdSlider.css";

interface Props {
  /** Used to gate the editor: only `admin` can change the threshold. */
  user?: CurrentUser | null;
}

/**
 *  — ADR-0011 kill-switch. Admin moves θ between 0 and 1;
 * non-admins see the value as read-only. Setting back to 1.0 disables
 * block-mode (annotate-only).
 */
export function MlThresholdSlider({ user }: Props) {
  const t = useT();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";

  const current = useQuery({
    queryKey: ["ml-threshold"],
    queryFn: () => api.mlThresholdGet(),
    staleTime: 30_000,
  });

  // Local draft so the slider doesn't fire one PUT per drag pixel.
  const [draft, setDraft] = useState<number | null>(null);

  useEffect(() => {
    if (draft == null && current.data?.value != null) {
      setDraft(current.data.value);
    }
  }, [current.data?.value, draft]);

  const update = useMutation({
    mutationFn: (value: number) => api.mlThresholdPut(value),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ml-threshold"] }),
  });

  if (current.isLoading) {
    return <p className="ml-threshold__hint">{t("ml.threshold.loading")}</p>;
  }

  const live = current.data?.value ?? 1.0;
  const dirty = draft != null && Math.abs(draft - live) > 1e-6;

  return (
    <section className="ml-threshold stack">
      <header>
        <span className="mono-label">{t("ml.threshold.kicker")}</span>
        <h2>{t("ml.threshold.title")}</h2>
        <p className="ml-threshold__hint">
          {live >= 1.0
            ? t("ml.threshold.off")
            : t("ml.threshold.on", { value: live.toFixed(2) })}
        </p>
      </header>

      <div className="ml-threshold__row">
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={draft ?? live}
          onChange={(e) => setDraft(parseFloat(e.target.value))}
          disabled={!isAdmin || update.isPending}
          aria-label={t("ml.threshold.title")}
        />
        <code className="ml-threshold__value">
          {(draft ?? live).toFixed(2)}
        </code>
      </div>

      {isAdmin && (
        <div className="row">
          <Button
            disabled={!dirty || update.isPending}
            onClick={() => draft != null && update.mutate(draft)}
          >
            {t("ml.threshold.apply")}
          </Button>
          <Button
            variant="ghost"
            disabled={live === 1.0 || update.isPending}
            onClick={() => update.mutate(1.0)}
          >
            {t("ml.threshold.rollback")}
          </Button>
        </div>
      )}

      {!isAdmin && (
        <p className="ml-threshold__hint">{t("ml.threshold.admin_only")}</p>
      )}

      {update.error && (
        <p role="alert" className="ml-threshold__error">
          {t("ml.threshold.error", { message: (update.error as Error).message })}
        </p>
      )}
    </section>
  );
}
