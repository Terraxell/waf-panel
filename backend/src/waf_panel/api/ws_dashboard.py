"""WebSocket endpoint for live Dashboard updates — task #122.

WHY: the SPA currently polls /metrics/overview every 30 s via React
Query. For a defensive panel the operator stares at during an attack,
30 s of staleness is forever. WS pushes the same payload every 5 s
without the per-poll auth round-trip cost.

Contract:
* URL: ``GET /api/v1/ws/dashboard`` (HTTP upgrade to WS)
* Auth: same cookie as REST -- ``waf_session`` JWT must be present and
  valid. Bearer header is also accepted for parity, though browsers
  cannot set custom headers on the WS handshake.
* Origin: must match one of ``settings.cors_origins``. Defence in
  depth against Cross-Site-WebSocket-Hijacking: SameSite=Strict on
  the cookie + Origin check is the standard mitigation since WS has
  no preflight.
* Payload: same shape as MetricsOverview, plus a ``generated_at`` ISO
  timestamp so the SPA can show "last updated 2 s ago".
* Tick: every ``WS_DASHBOARD_TICK_SEC`` env (default 5 s).

Fail-soft: ClickHouse error → send an empty overview with the
generated_at field set. The SPA falls back to its REST query.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from ..clickhouse_client import get_clickhouse
from ..config import get_settings
from ..security import JWTError, decode_access_token

log = logging.getLogger("waf-panel.ws.dashboard")

UTC = timezone.utc

router = APIRouter(prefix="/ws", tags=["ws"])

WS_DASHBOARD_TICK_ENV = "WS_DASHBOARD_TICK_SEC"
WS_DASHBOARD_TICK_DEFAULT = 5.0


def _tick_seconds() -> float:
    """Read the tick interval from env, default 5 s. Tests override to
    speed up the loop."""
    raw = os.environ.get(WS_DASHBOARD_TICK_ENV, "")
    if not raw:
        return WS_DASHBOARD_TICK_DEFAULT
    try:
        return max(0.05, float(raw))
    except ValueError:
        return WS_DASHBOARD_TICK_DEFAULT


def _origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    """Cross-Site WebSocket Hijacking guard. Empty / missing Origin is
    accepted because non-browser clients (CLI / pytest TestClient) do
    not send one; browsers always do."""
    if not origin:
        return True
    return origin in allowed


async def _build_overview_payload() -> dict[str, Any]:
    """Same query as /metrics/overview, but inline so the WS endpoint
    is independent of the REST handler's dependency graph (no Request
    object means no Depends() machinery)."""
    ch = get_clickhouse()
    try:
        rows = await ch.query_json(
            """
            SELECT
                count()                                 AS total,
                countIf(event_type = 'modsec')          AS blocked,
                uniqExact(remote_ip)                    AS uniq_ips
            FROM traffic_log
            WHERE ts > now() - INTERVAL 24 HOUR
            """
        )
        head = rows[0] if rows else {"total": 0, "blocked": 0, "uniq_ips": 0}
        total = int(head.get("total", 0))
        blocked = int(head.get("blocked", 0))

        top_rows = await ch.query_json(
            """
            SELECT path, sum(hits) AS hits
            FROM top_attacks_lifetime
            WHERE bucket_day >= today() - 1
            GROUP BY path
            ORDER BY hits DESC
            LIMIT 10
            """
        )
        top = [
            {"path": str(r.get("path", "")), "hits": int(r.get("hits", 0))}
            for r in top_rows
        ]
        share = (blocked / total) if total > 0 else 0.0
        return {
            "requests_24h": total,
            "blocked_24h": blocked,
            "blocked_share": share,
            "unique_ips_24h": int(head.get("uniq_ips", 0)),
            "top_attacks": top,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    except Exception as e:  # noqa: BLE001 -- fail-soft per contract
        log.warning("ws dashboard CH query failed: %s", e)
        return {
            "requests_24h": 0,
            "blocked_24h": 0,
            "blocked_share": 0.0,
            "unique_ips_24h": 0,
            "top_attacks": [],
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "fallback": True,
        }


@router.websocket("/dashboard")
async def dashboard_ws(websocket: WebSocket) -> None:
    settings = get_settings()

    # 1. Origin check (CSWSH defence)
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin, settings.cors_origins):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="origin not allowed",
        )
        return

    # 2. Auth: cookie or Bearer header
    token = websocket.cookies.get(settings.cookie_session_name)
    if not token:
        # Browsers don't set custom headers on the WS handshake but the
        # FastAPI TestClient does, and CLI consumers might.
        auth_hdr = websocket.headers.get("authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            token = auth_hdr.split(None, 1)[1]
    if not token:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="not authenticated",
        )
        return
    try:
        decode_access_token(token)
    except JWTError:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="invalid token",
        )
        return

    # 3. Accept and start the tick loop
    await websocket.accept()
    tick = _tick_seconds()
    try:
        while True:
            payload = await _build_overview_payload()
            await websocket.send_json(payload)
            await asyncio.sleep(tick)
    except WebSocketDisconnect:
        # Normal shutdown -- the client closed the tab or navigated away.
        return
    except Exception as e:  # noqa: BLE001
        log.warning("ws dashboard loop crashed: %s", e)
        # Best-effort close. send_json may have already failed because
        # the socket is dead; contextlib.suppress hides the secondary error.
        with contextlib.suppress(Exception):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


__all__ = ["router"]
