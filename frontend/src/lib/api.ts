// Tiny typed fetch wrapper — cookie-auth + double-submit CSRF (ADR-0014).
//
// Two important defaults applied to every request:
//
//   1. ``credentials: 'include'`` — the browser attaches the httpOnly
//      ``waf_session`` cookie to same-origin calls, so we never
//      handle the JWT in JS.
//   2. On mutating verbs (POST/PUT/PATCH/DELETE) we add the
//      ``X-CSRF-Token`` header read from the in-memory store. The
//      backend compares it against the ``waf_csrf`` cookie; if they
//      don't match it returns 403.

import { clearAuth, getCsrfToken, setCsrfToken } from "./auth";
import type {
  ApiError, AuditEntry, CsrfOut, CurrentUser, IncidentFilters, IncidentRow,
  MetricsOverview, MlExplainResponse, MlInspectRequest, MlInspectResponse,
  MlThresholdResponse, RuleCreate, RuleOut, TimeBucket, TokenOut,
  DriftReportFull, DriftReportSummary,
  UserCreate, UserSummary, UserUpdate,
} from "./types";

const BASE = "/api/v1";

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");

  // Attach CSRF token on mutating verbs. The backend exempts safe
  // methods (skip), login/logout (chicken-and-egg), and Bearer-auth
  // requests (no implicit credential). On the SPA path we always have
  // a cookie, so for the verbs the middleware actually checks we want
  // the header set. Sending it on /auth/login or /auth/logout is
  // harmless — those endpoints ignore it.
  const method = (init.method ?? "GET").toUpperCase();
  if (MUTATING.has(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  const res = await fetch(BASE + path, {
    ...init,
    headers,
    credentials: "include",
  });

  if (!res.ok) {
    // 401 means the session is gone — either the cookie expired or was
    // cleared server-side. Drop our mirrored state so RequireAuth bounces
    // the user to /login on the next render.
    if (res.status === 401) clearAuth();
    const message = await safeMessage(res);
    const err: ApiError = { status: res.status, message };
    throw err;
  }
  // 204 has no body. 200 may also have an empty body — /auth/logout
  // returns 200 with no content because Starlette strips Set-Cookie on
  // 204 and we still need the cookie-deletion headers to ride along.
  if (res.status === 204) return undefined as T;
  const contentLength = res.headers.get("content-length");
  if (contentLength === "0") return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

async function safeMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data === "object" && data && "detail" in data) {
      return String((data as Record<string, unknown>).detail);
    }
    return res.statusText || `HTTP ${res.status}`;
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const parts = Object.entries(params).flatMap(([k, v]) =>
    v === undefined || v === "" ? [] : [`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`]
  );
  return parts.length === 0 ? "" : "?" + parts.join("&");
}

export const api = {
  login: async (email: string, password: string): Promise<TokenOut> => {
    const out = await request<TokenOut>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setCsrfToken(out.csrf_token);
    return out;
  },
  logout: async (): Promise<void> => {
    try {
      await request<void>("/auth/logout", { method: "POST" });
    } catch {
      /* ignore — local cleanup matters more than the round-trip */
    }
    clearAuth();
  },
  me: () => request<CurrentUser>("/auth/me"),
  refreshCsrf: async (): Promise<string> => {
    const out = await request<CsrfOut>("/auth/csrf");
    setCsrfToken(out.csrf_token);
    return out.csrf_token;
  },

  listRules: () => request<RuleOut[]>("/rules"),
  createRule: (payload: RuleCreate) =>
    request<RuleOut>("/rules", { method: "POST", body: JSON.stringify(payload) }),
  deleteRule: (id: string) => request<void>(`/rules/${id}`, { method: "DELETE" }),

  metricsOverview: () => request<MetricsOverview>("/metrics/overview"),
  metricsTimeseries: (bucket: "minute" | "hour" = "minute", since_hours = 1) =>
    request<TimeBucket[]>(`/metrics/timeseries${qs({ bucket, since_hours })}`),

  listIncidents: (f: IncidentFilters = {}) =>
    request<IncidentRow[]>(`/incidents${qs({
      since_hours: f.since_hours,
      ip: f.ip,
      method: f.method,
      only_blocked: f.only_blocked,
      limit: f.limit,
    })}`),

  listAudit: (limit = 100, action_prefix?: string) =>
    request<AuditEntry[]>(`/audit${qs({ limit, action_prefix })}`),
  // ── Users (#123 admin-only management) ────────────────────────────
  listUsers: () => request<UserSummary[]>("/users"),
  createUser: (payload: UserCreate) =>
    request<UserSummary>("/users", { method: "POST", body: JSON.stringify(payload) }),
  updateUser: (id: string, patch: UserUpdate) =>
    request<UserSummary>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteUser: (id: string) =>
    request<void>(`/users/${id}`, { method: "DELETE" }),

  // ── Drift reports ──────────────────────────────────────────────────
  listDriftReports: () => request<DriftReportSummary[]>("/drift"),
  getDriftReport: (name: string) =>
    request<DriftReportFull>(`/drift/${encodeURIComponent(name)}`),


  mlInspect: (req: MlInspectRequest) =>
    request<MlInspectResponse>("/ml/inspect", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  mlExplain: (req: MlInspectRequest, top_k = 5) =>
    request<MlExplainResponse>(`/ml/explain${qs({ top_k })}`, {
      method: "POST",
      body: JSON.stringify(req),
    }),

  mlThresholdGet: () => request<MlThresholdResponse>("/ml/threshold"),
  mlThresholdPut: (value: number) =>
    request<MlThresholdResponse>("/ml/threshold", {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
};
