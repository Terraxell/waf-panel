// In-memory token store .
// SAFETY: nothing persisted to localStorage on purpose — see ADR-0003.
//  replaces this with HTTP-only cookies.

let token: string | null = null;
const listeners = new Set<() => void>();

export function getToken(): string | null {
  return token;
}

export function setToken(next: string | null): void {
  token = next;
  listeners.forEach((fn) => fn());
}

export function isAuthenticated(): boolean {
  return token !== null;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
