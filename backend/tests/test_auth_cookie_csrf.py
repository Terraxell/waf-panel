"""Cookie auth + double-submit CSRF — ADR-0014.

Three groups of behaviours we lock down:

1. **Login plants both cookies + returns CSRF token in body.**
   The SPA needs the body value on first paint; the cookies are how
   the browser carries credentials across requests.

2. **CSRF middleware skip rules.**
   - Safe methods (GET) never blocked.
   - Bearer-authenticated mutating requests never blocked (CLI/CI).
   - login/logout themselves never blocked (chicken-and-egg).
   - Cookie-authenticated mutating requests need the matching header.

3. **/auth/me works via either auth path.**
   Existing Bearer tests already cover the header path; here we
   prove the cookie path produces the same CurrentUser.
"""

from __future__ import annotations


def _login(client) -> tuple[str, str]:
    """Log in via the standard fixture admin and return (jwt, csrf).

    The TestClient retains cookies across calls automatically, so the
    caller doesn't need to re-attach anything for subsequent cookie
    auth — the relevant cookies are already in ``client.cookies``.
    """
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    return body["access_token"], body["csrf_token"]


# ── 1. Login plants both cookies and returns the CSRF in the body ────


def test_login_returns_access_token_and_csrf(client) -> None:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert res.status_code == 200
    body = res.json()
    # Bearer token still present for CLI compatibility.
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert body["token_type"] == "bearer"
    # New: CSRF token surfaces in the body so the SPA doesn't have to
    # read document.cookie immediately after login.
    assert isinstance(body["csrf_token"], str)
    assert len(body["csrf_token"]) >= 32  # token_urlsafe(32) → ~43 chars


def test_login_sets_session_and_csrf_cookies(client) -> None:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert res.status_code == 200
    cookies = res.headers.get_list("set-cookie")
    joined = "\n".join(cookies)
    # Session cookie is httpOnly — JS can't read it.
    assert "waf_session=" in joined
    assert "HttpOnly" in joined
    # SameSite=Strict is the second line of CSRF defence (browsers
    # vary on its enforcement; we still depend on the double-submit
    # below for correctness).
    assert "SameSite=strict" in joined.lower() or "samesite=strict" in joined.lower()
    # CSRF cookie is JS-readable — must NOT have HttpOnly. Find its
    # line specifically and check.
    csrf_line = next(c for c in cookies if c.startswith("waf_csrf="))
    assert "HttpOnly" not in csrf_line


# ── 2. CSRF middleware behaviour ────────────────────────────────────


def test_get_request_never_needs_csrf(client) -> None:
    """Safe methods are exempt — they don't mutate state."""
    _login(client)
    # Strip the CSRF header explicitly: GET should still pass.
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200


def test_bearer_auth_bypasses_csrf_check(client) -> None:
    """CLI/CI use Bearer; the browser cookie is not implicit there,
    so CSRF is moot. Mutating request without X-CSRF-Token must pass
    when auth comes via Authorization header."""
    token, _csrf = _login(client)

    # Important: clear cookies so the request looks like a CLI call,
    # not a browser. Otherwise the middleware sees both cookie AND
    # bearer and the bearer wins by design.
    client.cookies.clear()

    payload = {
        "rule_key": "csrf-bypass-bearer",
        "source": "custom",
        "severity": 3,
        "action": "log",
        "description": "bearer should bypass CSRF",
        "body": "SecRule ARGS \"@rx x\" \"id:9999,phase:2,deny\"",
        "enabled": True,
    }
    res = client.post(
        "/api/v1/rules",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    # 201 created; the test isn't about rules logic but about CSRF
    # not blocking a Bearer-auth POST.
    assert res.status_code in (200, 201), res.text


def test_cookie_auth_without_csrf_header_is_403(client) -> None:
    """The whole point of CSRF protection: cookie alone, no header → 403."""
    _login(client)  # cookies now in client.cookies

    payload = {
        "rule_key": "csrf-missing-header",
        "source": "custom",
        "severity": 3,
        "action": "log",
        "description": "should be blocked",
        "body": "SecRule ARGS \"@rx x\" \"id:9998,phase:2,deny\"",
        "enabled": True,
    }
    # No Authorization header, no X-CSRF-Token: cookie-only, should fail.
    res = client.post("/api/v1/rules", json=payload)
    assert res.status_code == 403, res.text
    assert "csrf" in res.json()["detail"].lower()


def test_cookie_auth_with_correct_csrf_header_passes(client) -> None:
    _, csrf = _login(client)

    payload = {
        "rule_key": "csrf-with-header",
        "source": "custom",
        "severity": 3,
        "action": "log",
        "description": "cookie + matching CSRF header",
        "body": "SecRule ARGS \"@rx x\" \"id:9997,phase:2,deny\"",
        "enabled": True,
    }
    res = client.post(
        "/api/v1/rules",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code in (200, 201), res.text


def test_cookie_auth_with_mismatched_csrf_header_is_403(client) -> None:
    _login(client)
    payload = {
        "rule_key": "csrf-mismatch",
        "source": "custom",
        "severity": 3,
        "action": "log",
        "description": "wrong header value",
        "body": "SecRule ARGS \"@rx x\" \"id:9996,phase:2,deny\"",
        "enabled": True,
    }
    res = client.post(
        "/api/v1/rules",
        json=payload,
        headers={"X-CSRF-Token": "obviously-not-the-real-token"},
    )
    assert res.status_code == 403


def test_login_endpoint_itself_is_csrf_exempt(client) -> None:
    """If the login endpoint required CSRF, no one could log in for
    the first time. The middleware must explicitly exempt it."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert res.status_code == 200


def test_logout_clears_cookies(client) -> None:
    _login(client)
    res = client.post("/api/v1/auth/logout")
    # WHY 200 not 204: Starlette drops Set-Cookie on 204; auth.py
    # returns 200 with empty body so the deletion headers ride along.
    assert res.status_code == 200
    cookies = res.headers.get_list("set-cookie")
    joined = "\n".join(cookies).lower()
    assert "waf_session=" in joined and "max-age=0" in joined
    assert "waf_csrf=" in joined


# ── 3. /auth/me works via cookie path ────────────────────────────────


def test_me_works_via_cookie(client) -> None:
    _login(client)
    # No Authorization header — only the cookie set by login.
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "admin@example.com"
    assert body["role"] == "admin"


def test_me_rejects_when_no_auth(client) -> None:
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


# ── 4. /auth/csrf refreshes the token ────────────────────────────────


def test_csrf_endpoint_returns_token_when_logged_in(client) -> None:
    _, original = _login(client)
    res = client.get("/api/v1/auth/csrf")
    assert res.status_code == 200
    fresh = res.json()["csrf_token"]
    assert fresh and fresh != original  # token rotated


def test_csrf_endpoint_401_without_session(client) -> None:
    res = client.get("/api/v1/auth/csrf")
    assert res.status_code
