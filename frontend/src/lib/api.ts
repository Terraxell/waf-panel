// Tiny typed fetch wrapper.

import { getToken } from "./auth";
import type {
  ApiError, AuditEntry, CurrentUser, IncidentFilters, IncidentRow,
  MetricsOverview, MlExplainResponse, MlInspectRequest, MlInspectResponse,
  MlThresholdResponse, RuleCreate, RuleOut, TimeBucket, TokenOut,
} from "./types";

const BASE = "/api/v1";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(BASE + path, { ...init, headers });
  if (!res.ok) {
    const message = await safeMessage(res);
    const err: ApiError = { status: res.status, message };
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
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
  login: (email: string, password: string) =>
    request<TokenOut>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => request<CurrentUser>("/auth/me"),

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

  // ── ML proxy ( + 9) ───────────────────────────────────────────
  // WHY: backend fails open, so the UI gets a stable envelope even when
  //      ml-service is down — `fallback: true` and `prob: null`.
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
