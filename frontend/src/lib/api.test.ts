// Cookie auth + double-submit CSRF — ADR-0014.
//
// We don't have a real backend in vitest, so we mock global.fetch and
// assert the request shape the wrapper produces. Three behaviours we
// lock down:
//
//   1. Every request goes out with `credentials: 'include'` so the
//      browser sends the httpOnly waf_session cookie.
//   2. Mutating verbs (POST/PUT/PATCH/DELETE) carry the `X-CSRF-Token`
//      header populated from the in-memory store.
//   3. Safe verbs (GET) do NOT carry the CSRF header. The backend
//      skips them anyway, but sending it would mask real bugs in the
//      mutating path.
//
// Plus a couple of smaller invariants: login caches the CSRF token,
// logout clears in-memory state, and a 401 response also clears it.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { clearAuth, getCsrfToken, isAuthenticated, setAuthed, setCsrfToken } from "./auth";

type FetchArgs = [RequestInfo | URL, RequestInit?];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function emptyResponse(status = 200): Response {
  // /auth/logout returns 200 with no body. content-length: 0 so the
  // wrapper short-circuits before trying to parse JSON.
  return new Response(null, {
    status,
    headers: { "content-length": "0" },
  });
}

const fetchMock = vi.fn<(...args: FetchArgs) => Promise<Response>>();

beforeEach(() => {
  fetchMock.mockReset();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  clearAuth();
});

afterEach(() => {
  clearAuth();
});

function lastInit(): RequestInit {
  const call = fetchMock.mock.calls.at(-1);
  if (!call) throw new Error("fetch was not called");
  return call[1] ?? {};
}

function lastHeaders(): Headers {
  const init = lastInit();
  return new Headers(init.headers);
}

describe("api wrapper — cookie + CSRF (ADR-0014)", () => {
  it("attaches credentials: 'include' on every request", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "x", email: "a@b", role: "admin", is_active: true }));
    await api.me();
    expect(lastInit().credentials).toBe("include");
  });

  it("does NOT send X-CSRF-Token on safe (GET) requests", async () => {
    setCsrfToken("csrf-abc");
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listRules();
    expect(lastHeaders().has("X-CSRF-Token")).toBe(false);
  });

  it("sends X-CSRF-Token on POST when the in-memory token is set", async () => {
    setCsrfToken("csrf-abc");
    fetchMock.mockResolvedValue(jsonResponse({}));
    await api.createRule({
      rule_key: "k",
      source: "custom",
      severity: 3,
      action: "log",
      description: "",
      body: "",
      enabled: true,
    });
    expect(lastHeaders().get("X-CSRF-Token")).toBe("csrf-abc");
  });

  it("sends X-CSRF-Token on DELETE", async () => {
    setCsrfToken("csrf-abc");
    fetchMock.mockResolvedValue(emptyResponse(204));
    await api.deleteRule("00000000-0000-0000-0000-000000000001");
    expect(lastHeaders().get("X-CSRF-Token")).toBe("csrf-abc");
  });

  it("sends X-CSRF-Token on PUT (ml threshold)", async () => {
    setCsrfToken("csrf-abc");
    fetchMock.mockResolvedValue(jsonResponse({ value: 0.5 }));
    await api.mlThresholdPut(0.5);
    expect(lastHeaders().get("X-CSRF-Token")).toBe("csrf-abc");
  });

  it("login response caches the CSRF token in the in-memory store", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        access_token: "jwt-not-used-by-spa",
        token_type: "bearer",
        expires_in: 1800,
        csrf_token: "fresh-csrf",
      }),
    );
    await api.login("admin@example.com", "admin");
    expect(getCsrfToken()).toBe("fresh-csrf");
  });

  it("logout clears in-memory auth state even on network failure", async () => {
    setCsrfToken("csrf-abc");
    setAuthed(true);
    fetchMock.mockRejectedValue(new TypeError("network down"));
    await api.logout();
    expect(getCsrfToken()).toBeNull();
    expect(isAuthenticated()).toBe(false);
  });

  it("a 401 response clears the in-memory session flag", async () => {
    setAuthed(true);
    setCsrfToken("csrf-abc");
    fetchMock.mockResolvedValue(jsonResponse({ detail: "not authenticated" }, 401));
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(isAuthenticated()).toBe(false);
    expect(getCsrfToken()).toBeNull();
  });

  it("refreshCsrf updates the in-memory token", async () => {
    setCsrfToken("old");
    fetchMock.mockResolvedValue(jsonResponse({ csrf_token: "new" }));
    const out = await api.refreshCsrf();
    expect(out).toBe("new");
    expect(getCsrfToken()).toBe("new");
  });

  it("does not crash on a 200 with empty body (logout path)", async () => {
    fetchMock.mockResolvedValue(emptyResponse(200));
    // logout uses POST to /auth/logout and expects no JSON parse.
    await expect(api.logout()).resolves.toBeUndefined();
  });
});
