"""Security-headers middleware — Sprint 13 (audit C-list item 15)."""

from __future__ import annotations

import pytest


def _hit_health(client) -> dict:
    """Hit a public, dependency-free endpoint just to bounce a response back."""
    r = client.get("/health")
    assert r.status_code == 200
    return dict(r.headers)


def test_csp_header_present_and_default(client):
    h = _hit_health(client)
    assert "content-security-policy" in {k.lower() for k in h}
    csp = h.get("content-security-policy") or h.get("Content-Security-Policy")
    assert "default-src 'self'" in csp
    # SAFETY: this assertion is the regression-protector for the policy
    # tightening — if anyone relaxes it without doing so deliberately,
    # the test catches it.
    assert "frame-ancestors 'none'" in csp


def test_x_frame_options_deny(client):
    h = _hit_health(client)
    assert h.get("x-frame-options", h.get("X-Frame-Options")) == "DENY"


def test_x_content_type_options_nosniff(client):
    h = _hit_health(client)
    assert (
        h.get("x-content-type-options", h.get("X-Content-Type-Options"))
        == "nosniff"
    )


def test_referrer_policy_is_strict_origin_when_cross_origin(client):
    h = _hit_health(client)
    val = h.get("referrer-policy", h.get("Referrer-Policy"))
    assert val == "strict-origin-when-cross-origin"


def test_permissions_policy_drops_sensitive_apis(client):
    h = _hit_health(client)
    val = h.get("permissions-policy", h.get("Permissions-Policy"))
    assert "camera=()" in val
    assert "geolocation=()" in val
    assert "microphone=()" in val


def test_hsts_only_on_https():
    """SAFETY: HSTS over plain HTTP is a misconfiguration. The middleware
    inspects request.url.scheme and skips the header on http://.
    """
    from fastapi.testclient import TestClient

    from waf_panel.main import create_app

    # TestClient defaults to http://testserver — HSTS must NOT be emitted.
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/health")
        assert "strict-transport-security" not in {k.lower() for k in r.headers}

    # Direct middleware unit-test for the https path: build a fake ASGI
    # request whose url.scheme is "https" and verify the header lands.
    import asyncio
    from starlette.requests import Request
    from starlette.responses import Response
    from waf_panel.security_headers import SecurityHeadersMiddleware

    async def _ok(_req):
        return Response("ok")

    mw = SecurityHeadersMiddleware(app=_ok)

    async def _drive():
        scope = {
            "type": "http", "method": "GET", "path": "/x", "scheme": "https",
            "query_string": b"", "headers": [], "server": ("test", 443),
            "client": ("127.0.0.1", 0),
        }
        req = Request(scope)
        resp = await mw.dispatch(req, _ok)
        return resp

    resp = asyncio.run(_drive())
    sts = resp.headers.get("strict-transport-security")
    assert sts is not None
    assert "max-age=" in sts
    assert "includeSubDomains" in sts


def test_existing_response_headers_are_not_overwritten():
    """SAFETY: setdefault, not __setitem__ — Lua subrequest's
    X-WAF-ML-Prob and similar must survive."""
    import asyncio
    from starlette.requests import Request
    from starlette.responses import Response
    from waf_panel.security_headers import SecurityHeadersMiddleware

    async def _custom_csp(_req):
        r = Response("ok")
        r.headers["Content-Security-Policy"] = "default-src 'none'"
        return r

    mw = SecurityHeadersMiddleware(app=_custom_csp)

    async def _drive():
        scope = {
            "type": "http", "method": "GET", "path": "/x", "scheme": "http",
            "query_string": b"", "headers": [], "server": ("test", 80),
            "client": ("127.0.0.1", 0),
        }
        req = Request(scope)
        resp = await mw.dispatch(req, _custom_csp)
        return resp

    resp = asyncio.run(_drive())
    assert resp.headers["Content-Security-Policy"] == "default-src 'none'"


@pytest.mark.parametrize(
    "header",
    [
        "content-security-policy",
        "x-frame-options",
        "x-content-type-options",
        "referrer-policy",
        "permissions-policy",
    ],
)
def test_security_headers_apply_to_every_endpoint(client, admin_token, header):
    """The middleware runs on /api/v1/* too, not just /health."""
    r = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert header in {k.lower() for k in r.headers}
