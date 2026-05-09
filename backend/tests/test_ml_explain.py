"""Backend ML proxy /explain — same fail-open semantics as /inspect."""

from __future__ import annotations

import httpx

_REQ = {
    "method": "GET",
    "path": "/login.php",
    "query": "id=1' UNION SELECT password FROM users--",
    "user_agent": "sqlmap/1.7.2",
}


def _auth(_client, admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_explain_passes_through_on_success(client, admin_token, monkeypatch):
    from waf_panel.api import ml as ml_api

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "prob": 0.94,
                "model": "xgboost",
                "model_version": "csic-2010-xgb-v1",
                "method": "feature_importances",
                "contributors": [
                    {"feature": "tok_union_select", "weight": 0.5},
                    {"feature": "ua_is_bot", "weight": 0.3},
                ],
                "fallback_reason": None,
            }

    class _Client:
        def __init__(self, *a, **kw):  # noqa: ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):  # noqa: ARG002
            return _Resp()

    monkeypatch.setattr(ml_api.httpx, "AsyncClient", _Client)

    r = client.post("/api/v1/ml/explain", json=_REQ, headers=_auth(client, admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "feature_importances"
    assert body["prob"] == 0.94
    assert len(body["contributors"]) == 2
    assert body["contributors"][0]["feature"] == "tok_union_select"
    assert body["fallback"] is False


def test_explain_fails_open_on_timeout(client, admin_token, monkeypatch):
    from waf_panel.api import ml as ml_api

    class _Client:
        def __init__(self, *a, **kw):  # noqa: ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):  # noqa: ARG002
            raise httpx.TimeoutException("budget")

    monkeypatch.setattr(ml_api.httpx, "AsyncClient", _Client)

    r = client.post("/api/v1/ml/explain", json=_REQ, headers=_auth(client, admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["prob"] is None
    assert body["fallback"] is True
    assert body["fallback_reason"] == "timeout"
    assert body["contributors"] == []
    assert body["method"] == "unsupported"


def test_explain_requires_auth(client):
    r = client.post("/api/v1/ml/explain", json=_REQ)
    assert r.status_code == 401


def test_explain_passes_top_k_in_url(client, admin_token, monkeypatch):
    """The proxy must forward the top_k query param to ml-service."""
    from waf_panel.api import ml as ml_api

    seen_urls: list[str] = []

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "prob": 0.5, "model": "lr", "model_version": "v0",
                "method": "coef", "contributors": [], "fallback_reason": None,
            }

    class _Client:
        def __init__(self, *a, **kw):  # noqa: ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, *a, **kw):  # noqa: ARG002
            seen_urls.append(url)
            return _Resp()

    monkeypatch.setattr(ml_api.httpx, "AsyncClient", _Client)
    r = client.post("/api/v1/ml/explain?top_k=7", json=_REQ, headers=_auth(client, admin_token))
    assert r.status_code == 200
    assert any("top_k=7" in u for u in seen_urls)
