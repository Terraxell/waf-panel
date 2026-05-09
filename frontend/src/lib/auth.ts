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
let authed = false