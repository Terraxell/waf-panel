"""Incidents endpoint — read-side over ClickHouse `traffic_log`.

scope: filtered listing only. Adds: incident-detail
view with full payload, ML-score breakdown, and per-incident actions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ..clickhouse_client import ClickHouseDep
from ..schemas import CurrentUser
from .auth import require_role

router = APIRouter(prefix="/incidents", tags=["incidents"])


class IncidentRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ts: datetime
    event_type: Literal["access", "modsec"]
    remote_ip: str
    method: str
    path: str
    status: int


def _safe_str(v: object) -> str:
    return str(v) if v is not None else ""


def _esc(value: str) -> str:
    """Escape a single-quoted SQL literal. Keep this conservative — the
    full filter set is small, no user-supplied SQL gets near it."""
    return value.replace("'", "''")


@router.get("", response_model=list[IncidentRow])
async def list_incidents(
    ch: ClickHouseDep,
    _: Annotated[CurrentUser, Depends(require_role("admin", "analyst", "viewer"))],
    since_hours: Annotated[int, Query(ge=1, le=168)] = 24,
    ip: Annotated[str | None, Query(max_length=64)] = None,
    method: Annotated[str | None, Query(max_length=8)] = None,
    only_blocked: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[IncidentRow]:
    where = [f"ts > now() - INTERVAL {since_hours} HOUR"]
    if only_blocked:
        where.append("event_type = 'modsec'")
    if ip:
        where.append(f"remote_ip = '{_esc(ip)}'")
    if method:
        where.append(f"method = '{_esc(method.upper())}'")
    where_sql = " AND ".join(where)

    rows = await ch.query_json(
        f"""
        SELECT ts, event_type, remote_ip, method, path, status
        FROM traffic_log
        WHERE {where_sql}
        ORDER BY ts DESC
        LIMIT {limit}
        """
    )
    out: list[IncidentRow] = []
    for r in rows:
        ts_raw = r.get("ts")
        if isinstance(ts_raw, str):
            try:
                ts_dt = datetime.fromisoformat(ts_raw.replace(" ", "T"))
            except ValueError:
                continue
        elif isinstance(ts_raw, datetime):
            ts_dt = ts_raw
        else:
            continue
        out.append(
            IncidentRow(
                ts=ts_dt,
                event_type=r.get("event_type", "access"),
                remote_ip=_safe_str(r.get("remote_ip")),
                method=_safe_str(r.get("method")),
                path=_safe_str(r.get("path")),
                status=int(r.get("status", 0)),
            )
        )
    return out


__all__ = ["IncidentRow", "router"]
