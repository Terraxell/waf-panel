// In-memory CSRF token + session flag — see ADR-0014.
//
// The JWT itself lives in a httpOnly cookie that JS cannot read; the
// browser attaches it to every same-origin request automatically. What
// JS still needs is:
//
//   1. The CSRF token, to put into the X-CSRF-Token header on every
//      mutating request (double-submit pattern).
//   2. A boolean "I'm logged in" signal, used by RequireAuth to gate
//      protected routes. We can't observe the httpOnly cookie from JS,
//      so we mirror the state here in a tiny store.

let csrfToken: string | null = null;
let authed = false;
const listeners = new Set<() => void>();

export function getCsrfToken(): string | null {
  return csrfToken;
}

export function setCsrfToken(next: string | null): void {
  csrfToken = next;
}

export function isAuthenticated(): boolean {
  return authed;
}

/**
 * Mark the session as established. Called after a successful /auth/login
 * response or after /auth/me confirms an existing session on app boot.
 */
export function setAuthed(next: boolean): void {
  authed = next;
  listeners.forEach((fn) => fn());
}

/**
 * Clear both pieces of in-memory auth state. Called on logout or when
 * the server returns 401 to a request that thought we were logged in.
 */
export function clearAuth(): void {
  csrfToken = null;
  if (authed) {
    authed = false;
    listeners.forEach((fn) => fn());
  }
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
