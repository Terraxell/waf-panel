import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";
import "./Audit.css";

export function Audit() {
  const t = useT();
  const { lang } = useI18n();
  const localeTag = (
    { ru: "ru-RU", en: "en-US", de: "de-DE", fr: "fr-FR" } as const
  )[lang];

  const [prefix, setPrefix] = useState("");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(100);

  const audit = useQuery({
    queryKey: ["audit", prefix || null, limit],
    queryFn: () => api.listAudit(limit, prefix || undefined),
    refetchInterval: 30_000,
  });

  return (
    <div className="audit stack">
      <header>
        <span className="mono-label">{t("audit.kicker")}</span>
        <h1>{t("audit.title")}</h1>
        <p className="audit__hint">{t("audit.hint")}</p>
      </header>

      <Input
        label={t("audit.filter_label")}
        placeholder={t("audit.filter_placeholder")}
        value={prefix}
        onChange={(e) => setPrefix(e.target.value)}
      />

      <Input
        label={t("audit.search_label")}
        placeholder={t("audit.search_placeholder")}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {audit.isLoading && <Skeleton lines={4} height="2rem" />}
      {audit.error && <p role="alert" className="audit__error">{t("audit.error")}</p>}

      {audit.data && (() => {
        // Client-side full-text search across the loaded window: action,
        // target, and any string in the payload.
        const q = search.trim().toLowerCase();
        const visible = q
          ? audit.data.filter((row) =>
              `${row.action} ${row.target} ${JSON.stringify(row.payload)}`
                .toLowerCase()
                .includes(q),
            )
          : audit.data;
        return (
        <table className="audit__table">
          <thead>
            <tr>
              <th>{t("audit.col.time")}</th>
              <th>{t("audit.col.action")}</th>
              <th>{t("audit.col.target")}</th>
              <th>{t("audit.col.actor")}</th>
              <th>Payload</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row, idx) => (
              <tr key={`${row.ts}-${idx}`}>
                <td>{new Date(row.ts).toLocaleString(localeTag)}</td>
                <td><code>{row.action}</code></td>
                <td><code className="audit__target">{row.target}</code></td>
                <td>{row.actor_id ? <code>{row.actor_id.slice(0, 8)}…</code> : "—"}</td>
                <td>
                  <code className="audit__payload">
                    {JSON.stringify(row.payload)}
                  </code>
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr><td colSpan={5} className="audit__empty">{t("audit.empty")}</td></tr>
            )}
          </tbody>
        </table>
        );
      })()}

      {audit.data && audit.data.length >= limit && (
        <div className="row" style={{ justifyContent: "center" }}>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setLimit((n) => n + 100)}
          >
            {t("audit.load_more")}
          </Button>
        </div>
      )}
    </div>
  );
}
