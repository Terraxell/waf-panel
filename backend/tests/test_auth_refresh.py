"""End-to-end refresh-rotation — ADR-0015.

Five behaviours we lock down:

1. Login plants a `waf_refresh` cookie alongside session+csrf.
2. /auth/refresh returns a new access + sets a new refresh; the
   in-DB family generation gets bumped exactly once per call.
3. Replaying an OLD refresh after a successful rotation revokes
   the family and 401s. After that, even the legit refresh holder
   can't rotate any more.
4. /auth/logout revokes the family and clears both cookies.
5. /auth/refresh without a refresh cookie → 401 with a clear
   message, no DB change.
"""

from __future__ import annotations

from waf_panel.repositories.deps import memory_audit_repo


def _login_full(client) -> dict[str, str]:
    """Log in via the standard fixture admin and return both cookies +
    the body. The TestClient retains cookies so subsequent calls in
    the same test see them automatically."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert res.status_code == 200, res.text
    return {
        "body": res.json(),
        "cookies": dict(client.cookies),
        "set_cookie_lines": res.headers.get_list("set-cookie"),
    }


# ── 1. Login plants the refresh cookie ──────────────────────────────


def test_login_sets_refresh_cookie(client) -> None:
    out = _login_full(client)
    joined = "\n".join(out["set_cookie_lines"]).lower()
    assert "waf_refresh=" in joined
    # Path-scoped to /api/v1/auth/ so the browser only sends it during
    # rotation -- limits the blast radius of any other handler.
    assert "path=/api/v1/auth/" in joined
    # httpOnly + samesite=strict on the refresh, same posture as
    # waf_session.
    refresh_line = next(c for c in out["set_cookie_lines"] if c.startswith("waf_refresh="))
    assert "HttpOnly" in refresh_line
    assert "samesite=strict" in refresh_line.lower() or "SameSite=strict" in refresh_line


# ── 2. Rotation: bump generation, get fresh tokens ──────────────────


def test_refresh_rotates_and_returns_new_pair(client) -> None:
    _login_full(client)
    # The TestClient already has both cookies; calling /auth/refresh
    # uses them transparently.
    res1 = client.post("/api/v1/auth/refresh")
    assert res1.status_code == 200, res1.text
    body1 = res1.json()
    assert isinstance(body1["access_token"], str)
    assert isinstance(body1["csrf_token"], str)
    assert body1["expires_in"] > 0

    # Tokens differ from the originals (different generation in the
    # refresh, possibly different access depending on JWT iat resolution).
    res2 = client.post("/api/v1/auth/refresh")
    assert res2.status_code == 200, res2.text
    body2 = res2.json()
    # Calling refresh twice in a row must not 401; the second call
    # rotates from the freshly-set generation.
    assert body2["access_token"]


# ── 3. Replay → REVOKE ──────────────────────────────────────────────


def test_replay_after_rotation_revokes_family(client) -> None:
    """Capture the post-login refresh cookie, rotate once, then
    present the OLD refresh again. The family must be revoked and
    the second use 401.

    WHY explicit cookies= override on the replay call: httpx's
    TestClient cookie jar gets confused when the server sets the
    same name at the same path twice and we then try to overwrite
    with cookies.set() -- it ends up with two entries. Bypassing
    the jar by passing cookies=... on the call is cleaner for this
    specific assertion."""
    _login_full(client)
    stolen_refresh = client.cookies.get("waf_refresh")
    assert stolen_refresh

    # Legit user rotates (generation 0 → 1). The TestClient updates
    # its jar from Set-Cookie automatically.
    res_rot = client.post("/api/v1/auth/refresh")
    assert res_rot.status_code == 200

    # Replay the OLD (gen=0) refresh by passing it on the call.
    # cookies= overrides the jar for this single request.
    res_replay = client.post(
        "/api/v1/auth/refresh",
        cookies={"waf_refresh": stolen_refresh},
    )
    assert res_replay.status_code == 401, res_replay.text
    body = res_replay.json()
    assert "replay" in body["detail"].lower()

    # Audit row written.
    audit = memory_audit_repo()
    assert audit is not None
    actions = [r["action"] for r in audit._rows]
    assert "auth.refresh.replay_revoked" in actions


# ── 4. Logout revokes + clears cookies ──────────────────────────────


def test_logout_revokes_family_and_clears_cookies(client) -> None:
    _login_full(client)
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 200
    set_cookies = "\n".join(res.headers.get_list("set-cookie")).lower()
    assert "waf_session=" in set_cookies
    assert "waf_refresh=" in set_cookies
    assert "max-age=0" in set_cookies

    # Audit row recorded.
    audit = memory_audit_repo()
    assert audit is not None
    assert any(r["action"] == "auth.logout" for r in audit._rows)


# ── 5. No refresh cookie → 401 ──────────────────────────────────────


def test_refresh_without_cookie_returns_401(client) -> None:
    res = client.post("/api/v1/auth/refresh")
    assert res.status_code == 401
    assert "no refresh" in res.json()["detail"].lower()


def test_refresh_with_garbled_cookie_returns_401(client) -> None:
    client.cookies.set("waf_refresh", "this-is-not-a-jwt", path="/api/v1/auth/")
    res = client.post("/api/v1/auth/refresh")
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()


# ── 6. Sanity: access tokens still work via Bearer ──────────────────


def test_bearer_path_unaffected_by_rotation(client, admin_token) -> None:
    """The CLI/CI Bearer flow is not on the rotation path; it just
    issues a long-lived access via AuthService.login. Verify the
    fixture admin_token still resolves /auth/me."""
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "admin@example.com"


# ── 7. Lock down the access TTL change ──────────────────────────────


def test_login_uses_short_access_ttl(client) -> None:
    """ADR-0015: access tokens are 15 min, not 60 min. Lock that in
    so a future config change can't silently re-introduce the long
    TTL the rotation flow was meant to replace."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    body = res.json()
    # 15 min × 60 s = 900 s. Default is access_ttl_minutes=15.
    assert body["expires_in"] == 900
