"""Drift-report API — Sprint 13 (audit C-list item 18c).

WHY: the drift worker writes JSON files under ``ml/drift_reports/``.
Operators currently SSH or `cat` them. This endpoint exposes the
list + a single report so the panel can render a viewer page.

Read-only on disk, RBAC analyst-or-higher (no admin escalation needed).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..schemas import CurrentUser
from .auth import require_role

log = logging.getLogger("waf-panel.api.drift")

router = APIRouter(prefix="/drift", tags=["drift"])

_VIEWER_OR_HIGHER = require_role("admin", "analyst", "viewer")

# WHY: env-driven so the backend container can mount the worker's
# output directory under whatever path the operator chose.
DRIFT_REPORTS_DIR_ENV = "DRIFT_REPORTS_DIR"
DRIFT_REPORTS_DIR_DEFAULT = "/app/ml/drift_reports"


def _reports_dir() -> Path:
    return Path(os.environ.get(DRIFT_REPORTS_DIR_ENV, DRIFT_REPORTS_DIR_DEFAULT))


class DriftReportSummary(BaseModel):
    name: str
    generated_at: str | None
    status: str
    alert_count: int
    warn_count: int
    n_rows_checked: int


class DriftReportFull(DriftReportSummary):
    n_features_compared: int = 0
    features: list[dict] = Field(default_factory=list)


@router.get("", response_model=list[DriftReportSummary])
async def list_reports(
    _: Annotated[CurrentUser, Depends(_VIEWER_OR_HIGHER)],
) -> list[DriftReportSummary]:
    """Newest reports first. Each report's filename is `drift-<TS>.json`."""
    d = _reports_dir()
    if not d.exists():
        return []

    out: list[DriftReportSummary] = []
    for p in sorted(d.glob("drift-*.json"), reverse=True):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 — fail-soft per file
            log.warning("skipping bad drift report %s: %s", p, e)
            continue
        out.append(DriftReportSummary(
            name=p.name,
            generated_at=payload.get("generated_at"),
            status=payload.get("status", "unknown"),
            alert_count=int(payload.get("alert_count", 0)),
            warn_count=int(payload.get("warn_count", 0)),
            n_rows_checked=int(payload.get("n_rows_checked", 0)),
        ))
    return out


@router.get("/{name}", response_model=DriftReportFull)
async def get_report(
    name: str,
    _: Annotated[CurrentUser, Depends(_VIEWER_OR_HIGHER)],
) -> DriftReportFull:
    """Full report by filename. SAFETY: filename is restricted to
    `drift-*.json`; we explicitly reject `..` traversal.
    """
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid report name")
    if not name.startswith("drift-") or not name.endswith(".json"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid report name")

    p = _reports_dir() / name
    if not p.exists() or not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("drift report %s unreadable: %s", p, e)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "unreadable report") from e

    return DriftReportFull(
        name=p.name,
        generated_at=payload.get("generated_at"),
        status=payload.get("status", "unknown"),
        alert_count=int(payload.get("alert_count", 0)),
        warn_count=int(payload.get("warn_count", 0)),
        n_rows_checked=int(payload.get("n_rows_checked", 0)),
        n_features_compared=int(payload.get("n_features_compared", 0)),
        features=list(payload.get("features", [])),
    )


__all__ = ["DriftReportFull", "DriftReportSummary", "router"]
