"""ML proxy — inspect a single HTTP request via the ml-service container.

WHY: the dashboard wants a probability-of-attack number for an arbitrary
HTTP-request shape (rule-editor preview, incident drill-down). The
gateway never imports sklearn — it forwards to ml-service over HTTP.

SAFETY:
- 20 ms total budget. Anything slower → fail-open response.
- Network errors / 5xx → fail-open response with `fallback_reason`.
- ML being broken NEVER raises a 5xx out of the panel API; UI shows `—`.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..config import get_settings
from ..schemas import CurrentUser
from .auth import require_role

log = logging.getLogger("waf-panel.api.ml")

router = APIRouter(prefix="/ml", tags=["ml"])

_VIEWER_OR_HIGHER = require_role("admin", "analyst", "viewer")


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    method: str = Field(default="GET", max_length=16)
    path: str = Field(default="/", max_length=4096)
    query: str = Field(default="", max_length=8192)
    body: str = Field(default="", max_length=65536)
    user_agent: str = Field(default="", max_length=1024)
    referer: str = Field(default="", max_length=1024)


FallbackReason = Literal[
    "no_active_model",
    "feature_error",
    "predict_error",
    "timeout",
    "error_5xx",
    "network",
]


class InspectResponse(BaseModel):
    """Mirrors ml-service ScoreResponse with fail-open extras."""
    prob: float | None
    model: str | None
    model_version: str | None
    latency_ms: float
    cached: bool
    fallback: bool = False
    fallback_reason: FallbackReason | None = None


def _fallback(reason: FallbackReason, latency_ms: float = 0.0) -> InspectResponse:
    return InspectResponse(
        prob=None, model=None, model_version=None,
        latency_ms=latency_ms, cached=False,
        fallback=True, fallback_reason=reason,
    )


@router.post("/inspect", response_model=InspectResponse)
async def inspect(
    req: InspectRequest,
    _: Annotated[CurrentUser, Depends(_VIEWER_OR_HIGHER)],
) -> InspectResponse:
    settings = get_settings()
    timeout_s = settings.ml_service_timeout_ms / 1000.0
    url = f"{settings.ml_service_url.rstrip('/')}/score"

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(url, json=req.model_dump())
    except httpx.TimeoutException:
        log.info("ml-service timed out after %s ms", settings.ml_service_timeout_ms)
        return _fallback("timeout")
    except httpx.HTTPError as e:
        log.warning("ml-service network error: %s", e)
        return _fallback("network")

    if r.status_code >= 500:
        log.warning("ml-service returned %d", r.status_code)
        return _fallback("error_5xx")
    if r.status_code >= 400:
        return _fallback("network")

    try:
        body = r.json()
    except ValueError:
        return _fallback("network")

    return InspectResponse(
        prob=body.get("prob"),
        model=body.get("model"),
        model_version=body.get("model_version"),
        latency_ms=float(body.get("latency_ms", 0.0)),
        cached=bool(body.get("cached", False)),
        fallback=body.get("prob") is None,
        fallback_reason=body.get("fallback_reason"),
    )


# ── /explain — Sprint 9 ─────────────────────────────────────────────────

class FeatureContribution(BaseModel):
    feature: str
    weight: float


class ExplainResponse(BaseModel):
    """Mirrors ml-service ExplainResponse + the same fail-open envelope."""
    prob: float | None
    model: str | None
    model_version: str | None
    contributors: list[FeatureContribution]
    method: Literal["coef", "feature_importances", "unsupported"]
    fallback: bool = False
    fallback_reason: FallbackReason | None = None


def _explain_fallback(reason: FallbackReason) -> ExplainResponse:
    return ExplainResponse(
        prob=None, model=None, model_version=None,
        contributors=[], method="unsupported",
        fallback=True, fallback_reason=reason,
    )


@router.post("/explain", response_model=ExplainResponse)
async def explain(
    req: InspectRequest,
    _: Annotated[CurrentUser, Depends(_VIEWER_OR_HIGHER)],
    top_k: int = 5,
) -> ExplainResponse:
    """Same fail-open semantics as /inspect; mirrors ml-service /explain."""
    settings = get_settings()
    timeout_s = settings.ml_service_timeout_ms / 1000.0
    url = f"{settings.ml_service_url.rstrip('/')}/explain?top_k={int(top_k)}"

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(url, json=req.model_dump())
    except httpx.TimeoutException:
        return _explain_fallback("timeout")
    except httpx.HTTPError:
        return _explain_fallback("network")

    if r.status_code >= 500:
        return _explain_fallback("error_5xx")
    if r.status_code >= 400:
        return _explain_fallback("network")

    try:
        body = r.json()
    except ValueError:
        return _explain_fallback("network")

    contributors = [
        FeatureContribution(**c) for c in (body.get("contributors") or [])
    ]
    return ExplainResponse(
        prob=body.get("prob"),
        model=body.get("model"),
        model_version=body.get("model_version"),
        contributors=contributors,
        method=body.get("method") or "unsupported",
        fallback=body.get("prob") is None,
        fallback_reason=body.get("fallback_reason"),
    )


# ── /threshold — Sprint 10 (Sprint 11: backed by ml_config Postgres table) ──
# WHY: ADR-0011 — operator-controllable, audited, RBAC-gated, rollback-able
# to 1.0 instantly. Storage now lives in `ml_config(key='ml_block_threshold')`
# via MlConfigRepo so multi-replica gateways stay in sync.

_THRESHOLD_KEY = "ml_block_threshold"
_THRESHOLD_DEFAULT = 1.0


class ThresholdGetResponse(BaseModel):
    value: float
    description: str = "Current ML block-mode threshold (1.0 = annotate-only)."


class ThresholdPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(ge=0.0, le=1.0)


_ADMIN_ONLY = require_role("admin")


def _parse_threshold(raw: str | None) -> float:
    """SAFETY: a corrupted ml_config row must NOT make the API 5xx. Fall
    back to the annotate-only default and let the operator notice via UI.
    """
    if raw is None:
        return _THRESHOLD_DEFAULT
    try:
        v = float(raw)
    except (TypeError, ValueError):
        log.warning("ml_config[%s] is non-numeric (%r); falling back to 1.0", _THRESHOLD_KEY, raw)
        return _THRESHOLD_DEFAULT
    return max(0.0, min(1.0, v))


@router.get("/threshold", response_model=ThresholdGetResponse)
async def get_threshold(
    _: Annotated[CurrentUser, Depends(_VIEWER_OR_HIGHER)],
) -> ThresholdGetResponse:
    from ..db.session import get_session
    from ..repositories.deps import get_ml_config_repo

    # WHY: small endpoint, manual session pull beats a deep refactor of
    #      every existing route. The session handles its own lifecycle.
    async for s in get_session():
        repo = await get_ml_config_repo(s)
        raw = await repo.get(_THRESHOLD_KEY)
        return ThresholdGetResponse(value=_parse_threshold(raw))
    return ThresholdGetResponse(value=_THRESHOLD_DEFAULT)


@router.put("/threshold", response_model=ThresholdGetResponse)
async def put_threshold(
    body: ThresholdPutRequest,
    actor: Annotated[CurrentUser, Depends(_ADMIN_ONLY)],
) -> ThresholdGetResponse:
    """SAFETY: admin-only. Setting value=1.0 disables block-mode (kill-switch)."""
    from ..db.session import get_session
    from ..repositories.deps import get_audit_repo, get_ml_config_repo

    async for s in get_session():
        cfg = await get_ml_config_repo(s)
        prev = _parse_threshold(await cfg.get(_THRESHOLD_KEY))
        new = float(body.value)
        await cfg.set(_THRESHOLD_KEY, str(new), updated_by=actor.id)

        audit = await get_audit_repo(s)
        await audit.record(
            actor_id=actor.id,
            action="ml.threshold.update",
            target="ml_config:threshold",
            payload={"prev": prev, "new": new},
        )
        log.info(
            "ml threshold changed by %s: %.4f → %.4f", actor.email, prev, new,
        )
        return ThresholdGetResponse(value=new)
    return ThresholdGetResponse(value=_parse_threshold(None))


def _reset_threshold_for_tests() -> None:
    """Test helper: snap the threshold back to 1.0 between cases.

    WHY: Sprint 11 — value lives in InMemoryMlConfigRepo; we poke its
    private dict directly because the helper has to be sync (pytest
    fixtures aren't async by default) and the in-memory mutation IS sync.
    """
    from ..repositories.deps import memory_ml_config_repo

    repo = memory_ml_config_repo()
    if repo is not None:
        repo._kv[_THRESHOLD_KEY] = str(_THRESHOLD_DEFAULT)  # noqa: SLF001

__all__ = [
    "ExplainResponse",
    "FeatureContribution",
    "InspectRequest",
    "InspectResponse",
    "ThresholdGetResponse",
    "ThresholdPutRequest",
    "_reset_threshold_for_tests",
    "router",
]
