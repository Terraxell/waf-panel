"""WebSocket Dashboard live updates — task #122.

Five behaviours we lock down:

1. Unauthenticated connect is rejected with WS 1008.
2. Bearer-authenticated connect succeeds and receives the first
   payload within a tick.
3. The payload shape matches MetricsOverview (+ generated_at field).
4. Disallowed Origin is rejected with 1008 even when auth is fine
   (Cross-Site WebSocket Hijacking defence).
5. Empty Origin (CLI / TestClient) is allowed -- otherwise we cannot
   test from pytest at all.
"""

from __future__ import annotations

import pytest
from starlette.testclient import WebSocketTestSession


# Speed up the loop so tests don't take 5 seconds each. The endpoint
# reads WS_DASHBOARD_TICK_SEC from the env on every connection.
@pytest.fixture(autouse=True)
def fast_tick(monkeypatch):
    monkeypatch.setenv("WS_DASHBOARD_TICK_SEC", "0.05")


def _login(client) -> str:
    """Return a Bearer token. Strips cookies so the test connects as
    a CLI client (no implicit cookie auth)."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    client.cookies.clear()
    return token


# ── 1. Auth gate ─────────────────────────────────────────────────────


def test_unauthenticated_connect_rejected(client) -> None:
    # Reaching the WS endpoint without a cookie or a Bearer header
    # should be refused at the handshake. Starlette's TestClient
    # raises WebSocketDisconnect when the server closes during connect.
    from starlette.websockets import WebSocketDisconnect
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/api/v1/ws/dashboard"),
    ):
        pass
    # 1008 = policy violation (auth failure here).
    assert exc.value.code == 1008


def test_invalid_token_rejected(client) -> None:
    from starlette.websockets import WebSocketDisconnect
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(
            "/api/v1/ws/dashboard",
            headers={"Authorization": "Bearer obviously-not-a-jwt"},
        ),
    ):
        pass
    assert exc.value.code == 1008


# ── 2 & 3. Authenticated connect produces a payload ─────────────────


def test_authenticated_connect_receives_payload(client) -> None:
    token = _login(client)
    with client.websocket_connect(
        "/api/v1/ws/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    ) as ws:
        ws: WebSocketTestSession
        msg = ws.receive_json()
    # Required fields per the contract.
    for field in (
        "requests_24h",
        "blocked_24h",
        "blocked_share",
        "unique_ips_24h",
        "top_attacks",
        "generated_at",
    ):
        assert field in msg, f"missing field: {field}"
    assert isinstance(msg["top_attacks"], list)
    assert isinstance(msg["generated_at"], str)


def test_payload_arrives_repeatedly(client) -> None:
    """The endpoint pushes on a tick, not just once. Lock it down so a
    future refactor doesn't accidentally close after the first send."""
    token = _login(client)
    with client.websocket_connect(
        "/api/v1/ws/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    ) as ws:
        first = ws.receive_json()
        second = ws.receive_json()
    # The two payloads should both have a generated_at; equality of
    # values is not asserted because in-memory ClickHouse seeds may
    # change between calls in some test orderings.
    assert "generated_at" in first
    assert "generated_at" in second


# ── 4 & 5. Origin check ──────────────────────────────────────────────


def test_disallowed_origin_rejected(client) -> None:
    """A browser request with an Origin header pointing to a domain
    outside cors_origins must be refused. SameSite=Strict on the
    cookie covers most cases, but the explicit check is the
    belt-and-suspenders the threat model demands."""
    from starlette.websockets import WebSocketDisconnect

    token = _login(client)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(
            "/api/v1/ws/dashboard",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://evil.example.com",
            },
        ),
    ):
        pass
    assert exc.value.code == 1008


def test_empty_origin_allowed(client) -> None:
    """No-Origin requests (CLI, pytest TestClient default) are
    allowed; the SameSite cookie attribute is what blocks browsers."""
    token = _login(client)
    with client.websocket_connect(
        "/api/v1/ws/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    ) as ws:
        msg = ws.receive_json()
    assert "generated_at" in msg
