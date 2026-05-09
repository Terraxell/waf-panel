import { FormEvent, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { MlBadge } from "@/components/ui/MlBadge";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { useI18n, useT } from "@/lib/i18n";
import type { IncidentFilters } from "@/lib/types";
import "./Incidents.css";

export function Incidents() {
  const t = useT();
  const { lang } = useI18n();

  // WHY: range labels are localised, so they live inside the component
  // body — useMemo keeps the array identity stable across renders that
  // don't change `lang`.
  const RANGES = useMemo(
    () => [
      { label: t("incidents.range_1h"), hours: 1 },
      { label: t("incidents.range_24h"), hours: 24 },
      { label: t("incidents.range_7d"), hours: 24 * 7 },
    ],
    [t],
  );

  const [filters, setFilters] = useState<IncidentFilters>({
    since_hours: 24,
    only_blocked: true,
    limit: 100,
  });
  const [ip, setIp] = useState("");
  const [method, setMethod] = useState("");
  // this release: client-side full-text search across the loaded rows.
  const [search, setSearch] = useState("");

  const incidents = useQuery({
    queryKey: ["incidents", filters],
    queryFn: () => api.listIncidents(filters),
  });

  function applyFilters(e: FormEvent) {
    e.preventDefault();
    setFilters((f) => ({
      ...f,
      ip: ip.trim() || undefined,
      method: method.trim() || undefined,
    }));
  }

  // Locale BCP-47 tag for date formatting — drives both `toLocaleString`
  // and any future `Intl` helper consistently.
  const localeTag = (
    { ru: "ru-RU", en: "en-US", de: "de-DE", fr: "fr-FR" } as const
  )[lang];

  return (
    <div className="incidents stack">
      <header>
        <span className="mono-label">{t("incidents.kicker")}</span>
        <h1>{t("incidents.title")}</h1>
        <p className="incidents__hint">{t("incidents.hint")}</p>
      </header>

      <form className="incidents__filters" onSubmit={applyFilters}>
        <div className="incidents__ranges">
          {RANGES.map((r) => (
            <Button
              key={r.hours}
              type="button"
              variant={filters.since_hours === r.hours ? "primary" : "ghost"}
              onClick={() => setFilters((f) => ({ ...f, since_hours: r.hours }))}
            >
              {r.label}
            </Button>
          ))}
        </div>

        <Input
          label={t("incidents.ip_label")}
          placeholder={t("incidents.ip_placeholder")}
          value={ip}
          onChange={(e) => setIp(e.target.value)}
        />
        <Input
          label={t("incidents.method_label")}
          placeholder={t("incidents.method_placeholder")}
          value={method}
          onChange={(e) => setMethod(e.target.value)}
        />

        <Input
          label={t("incidents.search_label")}
          placeholder={t("incidents.search_placeholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <label className="incidents__only-blocked">
          <input
            type="checkbox"
            checked={filters.only_blocked ?? true}
            onChange={(e) => setFilters((f) => ({ ...f, only_blocked: e.target.checked }))}
          />
          <span className="mono-label">{t("incidents.only_blocked")}</span>
        </label>

        <Button type="submit">{t("incidents.apply")}</Button>
      </form>

      {incidents.isLoading && <Skeleton lines={4} height="2rem" />}
      {incidents.error && (
        <p role="alert" className="incidents__error">{t("incidents.error")}</p>
      )}

      {incidents.data && (() => {
        // WHY: client-side filter on top of the server-side fetched window.
        // Cheap (≤ filters.limit rows), no extra round-trip.
        const q = search.trim().toLowerCase();
        const visible = q
          ? incidents.data.filter((row) =>
              `${row.remote_ip} ${row.path} ${row.method}`.toLowerCase().includes(q),
            )
          : incidents.data;
        return (
        <table className="incidents__table">
          <thead>
            <tr>
              <th>{t("incidents.col.time")}</th>
              <th>{t("incidents.col.type")}</th>
              <th>{t("incidents.col.ip")}</th>
              <th>{t("incidents.col.method")}</th>
              <th>{t("incidents.col.path")}</th>
              <th>{t("incidents.col.status")}</th>
              <th>{t("incidents.col.ml")}</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row, idx) => (
              <tr key={`${row.ts}-${idx}`}>
                <td>{new Date(row.ts).toLocaleString(localeTag)}</td>
                <td><span className="mono-label">{row.event_type}</span></td>
                <td><code>{row.remote_ip}</code></td>
                <td><span className="mono-label">{row.method}</span></td>
                <td><code className="incidents__path">{row.path}</code></td>
                <td>{row.status}</td>
                <td>
                  <MlBadge
                    request={{
                      method: row.method,
                      path: row.path,
                      query: "",
                      user_agent: "",
                    }}
                  />
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr><td colSpan={7} className="incidents__empty">{t("incidents.empty")}</td></tr>
            )}
          </tbody>
        </table>
        );
      })()}

      {/* this release: paginated "Load more" — bumps the server-side `limit`
          in steps of +100. Rendered only when the page is full (a heuristic
          for "there might be more"). */}
      {incidents.data && incidents.data.length >= (filters.limit ?? 100) && (
        <div className="row" style={{ justifyContent: "center" }}>
          <Button
            type="button"
            variant="ghost"
            onClick={() =>
              setFilters((f) => ({ ...f, limit: (f.limit ?? 100) + 100 }))
            }
          >
            {t("incidents.load_more")}
          </Button>
        </div>
      )}
    </div>
  );
}
