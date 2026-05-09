"""Backend ML proxy — fail-open semantics under every failure mode.

WHY: ml-service is best-effort. The proxy must NEVER 5xx out of the
panel API just because ML is slow / down / wrong-shaped.
"""

from __future__ import annotations

import httpx
import pytest

_GOLDEN_REQUEST = {
    "method": "GET",
    "path": "/login.php",
    "query": "id=1' UNION SELECT password FROM users--",
    "body": "",
    "user_agent": "sqlmap/1.7.2",
}


def _auth(client, admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_inspect_passes_through_on_success(client, admin_token, monkeypatch):
    """Happy path: ml-service returns a probability — proxy mirrors it."""
    from waf_panel.api import ml as ml_api

    class _StubResponse:
        status_code = 200

        def json(self):
            return {
                "prob": 0.987,
                "model": "xgboost",
                "model_version": "csic-2010-xgb-v1",
                "latency_ms": 4.3,
                "cached": False,
                "fallback_reason": None,
            }

    class _StubClient:
        def __init__(self, *a, **kw):  # noqa: ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, _url, json=None):  # noqa: ARG002
            return _StubResponse()

    monkeypatch.setattr(ml_api.httpx, "AsyncClient", _StubClient)

    r = client.post("/api/v1/ml/inspect", json=_GOLDEN_REQUEST, headers=_auth(client, admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["prob"] == pytest.approx(0.987)
    assert body["model"] == "xgboost"
    assert body["model_version"] == "csic-2010-xgb-v1"
    assert body["fallback"] is False
    assert body["fallback_reason"] is None


def test_inspect_fails_open_on_timeout(client, admin_token, monkeypatch):
    from waf_panel.api import ml as ml_api

    class _TimeoutClient:
        def __init__(self, *a, **kw):  # noqa: ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):  # noqa: ARG002
            raise httpx.TimeoutException("budget exhausted")

    monkeypatch.setattr(ml_api.httpx, "AsyncClient", _TimeoutClient)

    r = client.post("/api/v1/ml/inspect", json=_GOLDEN_REQUEST, headers=_auth(client, admin_token))
    assert r.status_code == 200  # SAFETY: ML failure must not 5xx the panel
    body = r.json()
    assert body["prob"] is None
    assert body["fallback"] is True
    assert body["fallback_reason"] == "timeout"


def test_inspect_fails_open_on_5xx(client, admin_token, monkeypatch):
    from waf_panel.api import ml as ml_api

    class _ServerErrorResponse:
        status_code = 503

        def json(self):  # pragma: no cover - never called when status >= 500
            return {}

    class _Client:
        def __init__(self, *a, **kw):  # noqa: ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):  # noqa: ARG002
            return _ServerErrorResponse()

    monkeypatch.setattr(ml_api.httpx, "AsyncClient", _Client)

    r = client.post("/api/v1/ml/inspect", json=_GOLDEN_REQUEST, headers=_auth(client, admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["prob"] is None
    assert body["fallback_reason"] == "error_5xx"


def test_inspect_fails_open_on_network_error(client, admin_token, monkeypatch):
    from waf_panel.api import ml as ml_api

    class _BrokenClient:
        def __init__(self, *a, **kw):  # noqa: ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):  # noqa: ARG002
            raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(ml_api.httpx, "AsyncClient", _BrokenClient)

    r = client.post("/api/v1/ml/inspect", json=_GOLDEN_REQUEST, headers=_auth(client, admin_token))
    assert r.status_code == 200
    assert r.json()["fallback_reason"] == "network"


def test_inspect_requires_auth(client):
    """Unauthenticated callers see 401, not a fallback response."""
    r = client.post("/api/v1/ml/inspect", json=_GOLDEN_REQUEST)
    assert r.status_code == 401


def test_inspect_propagates_no_active_model_signal(client, admin_token, monkeypatch):
    """ml-service explicitly says 'no model' → proxy mirrors with prob=None."""
    from waf_panel.api import ml as ml_api

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "prob": None, "model": None, "model_version": None,
                "latency_ms": 0.0, "cached": False,
                "fallback_reason": "no_active_model",
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

    r = client.post("/api/v1/ml/inspect", json=_GOLDEN_REQUEST, headers=_auth(client, admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["prob"] is None
    assert body["fallback"] is True
    assert body["fallback_reason"] == "no_active_model"
