"""Metrics endpoints — aggregates pulled from ClickHouse.

Sprint 6: hot reads (`timeseries` and `top_attacks`) hit materialized
views (`rps_per_minute`, `top_attacks_lifetime`) instead of scanning
`traffic_log`. See ADR-0006.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ..clickhouse_client import ClickHouseDep
from ..schemas import CurrentUser
from .auth import require_role

router = APIRouter(prefix="/metrics", tags=["metrics"])


class TopAttack(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    path: str
    hits: int


class MetricsOverview(BaseModel):
    requests_24h: int
    blocked_24h: int
    blocked_share: float
    unique_ips_24h: int
    top_attacks: list[TopAttack]


class TimeBucket(BaseModel):
    bucket: datetime
    rps: float
    blocked: int


_VIEWER_OR_HIGHER = require_role("admin", "analyst", "viewer")


@router.get("/overview", response_model=MetricsOverview)
async def overview(
    ch: ClickHouseDep,
    _: Annotated[CurrentUser, Depends(_VIEWER_OR_HIGHER)],
) -> MetricsOverview:
    # Counters: still go to traffic_log because uniqExact on remote_ip
    # cannot be pre-aggregated by SummingMergeTree (needs HLL state).
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

    # Top attacks: use the materialized view, summed over the last 24h
    # of `bucket_day`. The 24h cutoff is approximate (day buckets), good
    # enough for the dashboard.
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
    top = [TopAttack(path=str(r.get("path", "")), hits=int(r.get("hits", 0))) for r in top_rows]

    share = (blocked / total) if total > 0 else 0.0
    return MetricsOverview(
        requests_24h=total,
        blocked_24h=blocked,
        blocked_share=share,
        unique_ips_24h=int(head.get("uniq_ips", 0)),
        top_attacks=top,
    )


@router.get("/timeseries", response_model=list[TimeBucket])
async def timeseries(
    ch: ClickHouseDep,
    _: Annotated[CurrentUser, Depends(_VIEWER_OR_HIGHER)],
    bucket: Annotated[Literal["minute", "hour"], Query()] = "minute",
    since_hours: Annotated[int, Query(ge=1, le=168)] = 1,
) -> list[TimeBucket]:
    if bucket == "minute":
        # WHY: the `rps_per_minute` MV already groups by minute. We just
        #      sum within the requested window.
        sql = f"""
        SELECT minute AS b, sum(total) / 60.0 AS rps, sum(blocked) AS blocked
        FROM rps_per_minute
        WHERE minute > now() - INTERVAL {since_hours} HOUR
        GROUP BY b
        ORDER BY b
        """
    else:
        # Hourly view: re-aggregate the per-minute MV.
        sql = f"""
        SELECT toStartOfHour(minute) AS b,
               sum(total) / 3600.0 AS rps,
               sum(blocked)        AS blocked
        FROM rps_per_minute
        WHERE minute > now() - INTERVAL {since_hours} HOUR
        GROUP BY b
        ORDER BY b
        """
    rows = await ch.query_json(sql)
    out: list[TimeBucket] = []
    for r in rows:
        b = r.get("b")
        if isinstance(b, str):
            try:
                b_dt = datetime.fromisoformat(b.replace(" ", "T"))
            except ValueError:
                continue
        elif isinstance(b, datetime):
            b_dt = b
        else:
            continue
        out.append(
            TimeBucket(
                bucket=b_dt,
                rps=float(r.get("rps", 0.0)),
                blocked=int(r.get("blocked", 0)),
            )
        )
    return out


__all__ = ["MetricsOverview", "TimeBucket", "TopAttack", "router"]
