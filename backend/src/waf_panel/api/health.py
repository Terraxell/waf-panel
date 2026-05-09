"""Liveness / readiness endpoint.

WHY: separate from the panel's /api/v1 surface so monitoring (and the compose
     healthcheck) can ping it without crossing auth or RBAC.
"""

from fastapi import APIRouter

from .. import __version__
from ..schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut, status_code=200)
async def health() -> HealthOut:
    # NOTE: components map is a placeholder; real readiness checks land in
    #       Sprint 4 once we wire SQLAlchemy and Redis.
    return HealthOut(version=__version__, components={"api": "ok"})
