import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";
import type { DriftFeatureRow } from "@/lib/types";
import "./Drift.css";

// WHY: backend writes drift-<TS>.json; the panel reads them so an
// operator never has to SSH into the worker pod for a verdict.

function levelClass(level: string): string {
  // Map the four levels (alert/warn/clean/ok) to a deterministic CSS
  // class so the dark/light theme tokens take care of contrast.
  return `drift-level drift-level--${level}`;
}

function fmtPsi(psi: number): string {
  return Number.isFinite(psi) ? psi.toFixed(3) : "—";
}

function fmtPvalue(p: number | null): string {
  if (p === null || !Number.isFinite(p)) return "—";
  return p < 0.001 ? p.toExponential(2) : p.toFixed(3);
}

function StatusBadge({ status }: { status: string }) {
  const label = status.toUpperCase();
  return <span className={levelClass(status)}>{label}</span>;
}

function ReportDetail({ name, onClose }: { name: string; onClose: () => void }) {
  const t = useT();
  const detail = useQuery({
    queryKey: ["drift", name],
    queryFn: () => api.getDriftReport(name),
  });

  return (
    <section className="drift-detail" aria-labelledby="drift-detail-title">
      <header className="drift-detail__header">
        <h2 id="drift-detail-title">{name}</h2>
        <button
          type="button"
          className="drift-detail__close"
          onClick={onClose}
          aria-label={t("drift.detail.close")}
        >
          ×
        </button>
      </header>

      {detail.isLoading && <Skeleton lines={6} height="1.5rem" />}
      {detail.error && (
        <p role="alert" className="drift-detail__error">
          {t("drift.detail.error")}
        </p>
      )}

      {detail.data && (
        <>
          <dl className="drift-detail__meta">
            <dt>{t("drift.col.status")}</dt>
            <dd><StatusBadge status={detail.data.status} /></dd>
            <dt>{t("drift.col.alerts")}</dt>
            <dd>{detail.data.alert_count}</dd>
            <dt>{t("drift.col.warns")}</dt>
            <dd>{detail.data.warn_count}</dd>
            <dt>{t("drift.col.rows")}</dt>
            <dd>{detail.data.n_rows_checked.toLocaleString()}</dd>
            <dt>{t("drift.detail.features_compared")}</dt>
            <dd>{detail.data.n_features_compared}</dd>
          </dl>

          {detail.data.features.length === 0 ? (
            <p className="drift-detail__empty">{t("drift.detail.no_features")}</p>
          ) : (
            <table className="drift-detail__table">
              <thead>
                <tr>
                  <th>{t("drift.detail.feature")}</th>
                  <th>PSI</th>
                  <th>KS p-value</th>
                  <th>{t("drift.col.status")}</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.features.map((f: DriftFeatureRow) => (
                  <tr key={f.feature}>
                    <td><code>{f.feature}</code></td>
                    <td>{fmtPsi(f.psi)}</td>
                    <td>{fmtPvalue(f.ks_pvalue)}</td>
                    <td><StatusBadge status={f.level} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

export function Drift() {
  const t = useT();
  const { lang } = useI18n();
  const localeTag = (
    { ru: "ru-RU", en: "en-US", de: "de-DE", fr: "fr-FR" } as const
  )[lang];

  const [selected, setSelected] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["drift", "list"],
    queryFn: () => api.listDriftReports(),
    refetchInterval: 60_000,
  });

  return (
    <div className="drift stack">
      <header>
        <span className="mono-label">{t("drift.kicker")}</span>
        <h1>{t("drift.title")}</h1>
        <p className="drift__hint">{t("drift.hint")}</p>
      </header>

      {list.isLoading && <Skeleton lines={4} height="2rem" />}
      {list.error && (
        <p role="alert" className="drift__error">{t("drift.error")}</p>
      )}

      {list.data && list.data.length === 0 && (
        <p className="drift__empty">{t("drift.empty")}</p>
      )}

      {list.data && list.data.length > 0 && (
        <table className="drift__table">
          <thead>
            <tr>
              <th>{t("drift.col.report")}</th>
              <th>{t("drift.col.generated")}</th>
              <th>{t("drift.col.status")}</th>
              <th>{t("drift.col.alerts")}</th>
              <th>{t("drift.col.warns")}</th>
              <th>{t("drift.col.rows")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((r) => (
              <tr
                key={r.name}
                className={`drift__row drift__row--${r.status}`}
                onClick={() => setSelected(r.name)}
                tabIndex={0}
                role="button"
                aria-label={`${r.name}, ${r.status}`}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelected(r.name);
                  }
                }}
              >
                <td><code>{r.name}</code></td>
                <td>
                  {r.generated_at
                    ? new Date(r.generated_at).toLocaleString(localeTag)
                    : "—"}
                </td>
                <td><StatusBadge status={r.status} /></td>
                <td>{r.alert_count}</td>
                <td>{r.warn_count}</td>
                <td>{r.n_rows_checked.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <ReportDetail name={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
