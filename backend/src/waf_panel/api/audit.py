"""Audit-log read-only endpoint. Admin-only."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ..repositories.deps import AuditRepoDep
from ..schemas import CurrentUser
from .auth import require_role

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    actor_id: UUID | None
    action: str
    target: str
    payload: dict[str, Any]


@router.get("", response_model=list[AuditEntry])
async def list_audit(
    audit: AuditRepoDep,
    _: Annotated[CurrentUser, Depends(require_role("admin"))],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    action_prefix: Annotated[str | None, Query(max_length=64)] = None,
) -> list[AuditEntry]:
    rows = await audit.recent(limit=limit)
    if action_prefix:
        rows = [r for r in rows if str(r.get("action", "")).startswith(action_prefix)]
    return [
        AuditEntry(
            ts=r["ts"],
            actor_id=r.get("actor_id"),
            action=str(r.get("action", "")),
            target=str(r.get("target", "")),
            payload=r.get("payload") or {},
        )
        for r in rows
    ]


__all__ = ["AuditEntry", "router"]
