import { useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import "./Dashboard.css";

function formatBucket(iso: string): string {
  // WHY: chart x-axis shows HH:MM; the full ISO is in the tooltip.
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function Dashboard() {
  const t = useT();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me() });
  const overview = useQuery({
    queryKey: ["metrics", "overview"],
    queryFn: () => api.metricsOverview(),
    refetchInterval: 30_000,
  });
  const series = useQuery({
    queryKey: ["metrics", "timeseries", "minute", 1],
    queryFn: () => api.metricsTimeseries("minute", 1),
    refetchInterval: 30_000,
  });
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api.listRules() });

  const ovr = overview.data;
  const chartData =
    series.data?.map((b) => ({ x: formatBucket(b.bucket), rps: b.rps, blocked: b.blocked })) ?? [];

  // Locale-aware number formatting — uses the browser's BCP47 default,
  // which respects the OS / browser language setting; we don't try to
  // override it from the i18n state because operators usually expect
  // their OS thousand-separator regardless of UI language.
  const numFmt = (n: number) => n.toLocaleString();

  return (
    <div className="dashboard stack">
      <header className="dashboard__head">
        <span className="mono-label">{t("dashboard.kicker")}</span>
        <h1>{t("dashboard.title")}</h1>
        <p className="dashboard__hint">{t("dashboard.hint")}</p>
      </header>

      <section className="dashboard__grid">
        <Card title={t("dashboard.card.user")} hint="GET /auth/me">
          <strong data-kind="text">{me.data?.email ?? "—"}</strong>
          <span className="mono-label">{me.data?.role ?? "—"}</span>
        </Card>

        <Card title={t("dashboard.card.requests")} hint="ClickHouse · count()">
          <strong>{ovr ? numFmt(ovr.requests_24h) : "—"}</strong>
          <span className="mono-label">{t("dashboard.card.requests_total")}</span>
        </Card>

        <Card title={t("dashboard.card.blocked")} hint="event_type='modsec'">
          <strong>{ovr ? numFmt(ovr.blocked_24h) : "—"}</strong>
          <span className="mono-label">
            {ovr
              ? t("dashboard.card.blocked_share", {
                  percent: (ovr.blocked_share * 100).toFixed(1),
                })
              : "—"}
          </span>
        </Card>

        <Card title={t("dashboard.card.unique_ips")} hint="uniqExact()">
          <strong>{ovr ? numFmt(ovr.unique_ips_24h) : "—"}</strong>
          <span className="mono-label">{t("dashboard.card.unique_ips_total")}</span>
        </Card>

        <Card title={t("dashboard.card.rules")} hint="GET /rules">
          <strong>{rules.data ? rules.data.length : "—"}</strong>
          <span className="mono-label">{t("dashboard.card.rules_total")}</span>
        </Card>

        <Card title={t("dashboard.card.ml_model")} hint="ml_models">
          <strong>—</strong>
          <span className="mono-label">{t("dashboard.card.ml_model_inactive")}</span>
        </Card>
      </section>

      <section className="dashboard__chart">
        <span className="mono-label">{t("dashboard.timeseries_label")}</span>
        <div style={{ height: 220 }}>
          <ResponsiveContainer>
            <AreaChart data={chartData} margin={{ top: 16, right: 16, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="g-rps" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--c-royal)" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="var(--c-royal)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="x" stroke="var(--c-sage)" fontSize={12} />
              <YAxis stroke="var(--c-sage)" fontSize={12} />
              <Tooltip
                contentStyle={{
                  background: "var(--c-white-pure)",
                  border: "1px solid var(--c-sage-soft)",
                  borderRadius: 0,
                }}
              />
              <Area type="monotone" dataKey="rps" stroke="var(--c-royal)" fill="url(#g-rps)" />
              <Area type="monotone" dataKey="blocked" stroke="var(--c-black)" fill="transparent" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="stack">
        <span className="mono-label">{t("dashboard.top_attacks_label")}</span>
        {ovr?.top_attacks?.length ? (
          <ul className="top-attacks">
            {ovr.top_attacks.map((a) => (
              <li key={a.path}>
                <code>{a.path}</code>
                <span>{a.hits}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="dashboard__hint">{t("dashboard.top_attacks_empty")}</p>
        )}
      </section>
    </div>
  );
}
