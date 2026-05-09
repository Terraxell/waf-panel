// Hand-written API types — mirror the FastAPI Pydantic schemas.
// WHY: ADR-0004 plans autogen from OpenAPI in future release.

export type RuleSource = "crs" | "custom" | "ml";
export type RuleAction = "block" | "log" | "challenge";
export type Role = "admin" | "analyst" | "viewer";
export type EventType = "access" | "modsec";

export interface CurrentUser {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
}

export interface TokenOut {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  // ADR-0014: backend returns the CSRF token in the body so the SPA
  // doesn't have to read document.cookie on first paint.
  csrf_token: string;
}

export interface CsrfOut {
  csrf_token: string;
}

export interface RuleOut {
  id: string;
  rule_key: string;
  source: RuleSource;
  severity: 1 | 2 | 3 | 4 | 5;
  action: RuleAction;
  description: string;
  body: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface RuleCreate {
  rule_key: string;
  source: RuleSource;
  severity: 1 | 2 | 3 | 4 | 5;
  action: RuleAction;
  description: string;
  body: string;
  enabled: boolean;
}

export interface TopAttack { path: string; hits: number; }
export interface MetricsOverview {
  requests_24h: number;
  blocked_24h: number;
  blocked_share: number;
  unique_ips_24h: number;
  top_attacks: TopAttack[];
}
export interface TimeBucket { bucket: string; rps: number; blocked: number; }
export interface IncidentRow {
  ts: string;
  event_type: EventType;
  remote_ip: string;
  method: string;
  path: string;
  status: number;
}
export interface IncidentFilters {
  since_hours?: number;
  ip?: string;
  method?: string;
  only_blocked?: boolean;
  limit?: number;
}

export interface AuditEntry {
  ts: string;
  actor_id: string | null;
  action: string;
  target: string;
  payload: Record<string, unknown>;
}

export interface ApiError { status: number; message: string; }

// ── ML proxy ( + 9) ─────────────────────────────────────────────
// WHY: matches the backend InspectResponse / ExplainResponse shapes —
//      nullable prob + fallback flag so the UI can render "—" cleanly.

export interface MlInspectRequest {
  method: string;
  path: string;
  query: string;
  body?: string;
  user_agent?: string;
  referer?: string;
}

export type MlFallbackReason =
  | "no_active_model"
  | "feature_error"
  | "predict_error"
  | "timeout"
  | "error_5xx"
  | "network";

export interface MlInspectResponse {
  prob: number | null;
  model: string | null;
  model_version: string | null;
  latency_ms: number;
  cached: boolean;
  fallback: boolean;
  fallback_reason: MlFallbackReason | null;
}

export interface MlContributor {
  feature: string;
  weight: number;
}

export type MlExplainMethod = "coef" | "feature_importances" | "shap" | "unsupported";

export interface MlExplainResponse {
  prob: number | null;
  model: string | null;
  model_version: string | null;
  contributors: MlContributor[];
  method: MlExplainMethod;
  fallback_reason: MlFallbackReason | null;
}

// ── Drift reports (C-list 18c, fronted by /api/v1/drift) ─────────
export type DriftLevel = "alert" | "warn" | "clean" | "ok";

export interface DriftFeatureRow {
  feature: string;
  psi: number;
  ks_pvalue: number | null;
  level: DriftLevel;
}

export interface DriftReportSummary {
  name: string;
  generated_at: string | null;
  status: string;
  alert_count: number;
  warn_count: number;
  n_rows_checked: number;
}

export interface DriftReportFull extends DriftReportSummary {
  n_features_compared: number;
  features: DriftFeatureRow[];
}
