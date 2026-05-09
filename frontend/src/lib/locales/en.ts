// English source-of-truth dictionary.
//
// WHY: EN is the canonical shape; RU is type-checked against it (see
// ./ru.ts). Add new keys here first, then mirror in ru.ts — TypeScript
// will fail the build until both sides match.
//
// Token interpolation: `{name}` placeholders. The runtime helper in
// `../i18n.tsx` substitutes them at call time.

export const en = {
  // ── Shell / nav ────────────────────────────────────────────────
  "nav.dashboard": "Dashboard",
  "nav.incidents": "Incidents",
  "nav.rules": "Rules",
  "nav.audit": "Audit",
  "nav.logout": "Sign out",
  "shell.lang_label": "Language",
  "shell.theme.label": "Theme",
  "shell.theme.light": "Light",
  "shell.theme.dark": "Dark",
  "shell.theme.auto": "Auto",

  // ── Login ──────────────────────────────────────────────────────
  "login.kicker": "waf-panel · sign in",
  "login.title": "WAF management",
  "login.hint": "Sign in to see incidents, rules and audit log. Default admin: {email} / {password}.",
  "login.email_label": "EMAIL",
  "login.password_label": "PASSWORD",
  "login.submit": "Sign in",
  "login.error_bad_creds": "Invalid email or password",
  "login.error_generic": "Sign-in error",
  "login.error_throttled": "Too many attempts. Try again in a minute.",

  // ── Dashboard ──────────────────────────────────────────────────
  "dashboard.kicker": "overview",
  "dashboard.title": "Stack status",
  "dashboard.hint": "Last 24 hours from ClickHouse, refreshed every 30 seconds.",
  "dashboard.card.user": "CURRENT USER",
  "dashboard.card.requests": "REQUESTS 24H",
  "dashboard.card.requests_total": "total",
  "dashboard.card.blocked": "BLOCKED 24H",
  "dashboard.card.blocked_share": "{percent} % of traffic",
  "dashboard.card.unique_ips": "UNIQUE IPS 24H",
  "dashboard.card.unique_ips_total": "sources",
  "dashboard.card.rules": "RULES",
  "dashboard.card.rules_total": "custom rules in total",
  "dashboard.card.ml_model": "ML MODEL",
  "dashboard.card.ml_model_inactive": "not activated",
  "dashboard.timeseries_label": "RPS AND BLOCKS — LAST HOUR",
  "dashboard.top_attacks_label": "TOP ATTACKS — 24H",
  "dashboard.top_attacks_empty": "No attacks recorded for this period.",

  // ── Incidents ──────────────────────────────────────────────────
  "incidents.kicker": "log",
  "incidents.title": "Incidents",
  "incidents.hint": "Requests blocked by CRS rules. Source: ClickHouse traffic_log.",
  "incidents.range_1h": "1H",
  "incidents.range_24h": "24H",
  "incidents.range_7d": "7D",
  "incidents.ip_label": "IP",
  "incidents.ip_placeholder": "e.g. 10.0.0.1",
  "incidents.method_label": "METHOD",
  "incidents.method_placeholder": "GET / POST",
  "incidents.only_blocked": "blocked only",
  "incidents.apply": "Apply",
  "incidents.loading": "Loading…",
  "incidents.error": "Failed to load incidents.",
  "incidents.col.time": "Time",
  "incidents.col.type": "Type",
  "incidents.col.ip": "IP",
  "incidents.col.method": "Method",
  "incidents.col.path": "Path",
  "incidents.col.status": "Status",
  "incidents.col.ml": "ML",
  "incidents.empty": "No incidents found for this period.",

  // ── Rules ──────────────────────────────────────────────────────
  "rules.kicker": "rules",
  "rules.title": "Rule editor",
  "rules.hint": "Custom rules live in PostgreSQL and sync to ModSecurity in Sprint 8. CRS rules (sourcetype=crs) ship with the image.",
  "rules.create_button": "New rule",
  "rules.loading": "Loading…",
  "rules.error": "Failed to load rules.",
  "rules.col.key": "Key",
  "rules.col.source": "Source",
  "rules.col.severity": "Severity",
  "rules.col.action": "Action",
  "rules.col.description": "Description",
  "rules.col.status": "Status",
  "rules.empty": "No custom rules created yet.",
  "rules.row.enabled": "enabled",
  "rules.row.disabled": "disabled",
  "rules.row.delete": "Delete",
  "rules.editor.kicker": "new rule",
  "rules.editor.title": "Create custom rule",
  "rules.editor.key_label": "KEY",
  "rules.editor.description_label": "DESCRIPTION",
  "rules.editor.enable_now": "enable immediately after saving",
  "rules.editor.save": "Save",
  "rules.editor.cancel": "Cancel",

  // ── Audit ──────────────────────────────────────────────────────
  "audit.kicker": "log",
  "audit.title": "Audit trail",
  "audit.hint": "Append-only log. Every mutation of rules, models and users leaves a trace here.",
  "audit.filter_label": "FILTER BY ACTION",
  "audit.filter_placeholder": "e.g. rule. or auth.login",
  "audit.loading": "Loading…",
  "audit.error": "Failed to load audit log.",
  "audit.col.time": "Time",
  "audit.col.action": "Action",
  "audit.col.target": "Target",
  "audit.col.actor": "Actor",
  "audit.empty": "No entries for this period.",

  // ── ML threshold slider ────────────────────────────────────────
  "ml.threshold.kicker": "ml block-mode",
  "ml.threshold.title": "Block threshold",
  "ml.threshold.loading": "Loading ML threshold…",
  "ml.threshold.off": "Block-mode disabled (annotate-only). Lower the threshold below 1.0 to enable.",
  "ml.threshold.on": "Block-mode active: requests with prob ≥ {value} will receive 403.",
  "ml.threshold.apply": "Apply",
  "ml.threshold.rollback": "Roll back (θ = 1.0)",
  "ml.threshold.admin_only": "Threshold change is admin-only.",
  "ml.threshold.error": "Failed to update threshold: {message}",

  // ── ML badge tooltip ───────────────────────────────────────────
  "ml.badge.unavailable": "ML unavailable: {reason}",
  "ml.badge.no_response": "no response",
  "ml.badge.prob": "prob = {value}",
  "ml.badge.model": "model: {name}",
  "ml.badge.cache_hit": "cache hit",
  "ml.badge.contributors": "contributors:",

  // ── Search + pagination (Sprint 12) ────────────────────────────
  "incidents.search_label": "SEARCH",
  "incidents.search_placeholder": "by IP / path",
  "incidents.load_more": "Load more",
  "audit.search_label": "SEARCH",
  "audit.search_placeholder": "by target / payload",
  "audit.load_more": "Load more",
} as const;

// WHY this maps to `string` (not `typeof en`): with `as const` above,
// every value becomes a string literal — useful for the EN side's own
// autocomplete, but it would force every translation to be the exact
// English string, which is the opposite of what we want. Mapping each
// key to `string` keeps the *key shape* as the contract (TS still fails
// the build if RU/DE/FR is missing or has an extra key) while letting
// values be any string the translator picked.
export type EnDict = { [K in keyof typeof en]: string };
