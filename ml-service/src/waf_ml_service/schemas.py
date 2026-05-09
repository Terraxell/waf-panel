"""Request / response shapes for /score and /explain.

WHY: Pydantic models give us OpenAPI for free, plus a stable contract the
backend proxy can typecheck against. Adding a field is a deliberate
breaking change — bump the schema version, update the proxy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScoreRequest(BaseModel):
    """One HTTP request to score. Mirrors the keys `featurize` expects."""

    model_config = ConfigDict(extra="ignore")

    method: str = Field(default="GET", max_length=16)
    path: str = Field(default="/", max_length=4096)
    query: str = Field(default="", max_length=8192)
    body: str = Field(default="", max_length=65536)
    user_agent: str = Field(default="", max_length=1024)
    referer: str = Field(default="", max_length=1024)
    headers: dict[str, str] | None = None


# WHY: explicit Literal so a typo in the proxy is a Pydantic error,
#      not a silent string mismatch.
FallbackReason = Literal[
    "no_active_model",
    "feature_error",
    "predict_error",
]


class ScoreResponse(BaseModel):
    prob: float | None
    model: str | None
    model_version: str | None
    latency_ms: float
    cached: bool
    fallback_reason: FallbackReason | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    model_loaded: bool
    model_version: str | None
    redis_ok: bool


class FeatureContribution(BaseModel):
    """One row in the /explain top-K list.

    weight is normalised so the top-K weights sum to 1.0 (by absolute
    magnitude); sign is preserved for LR (`coef`) so the UI can colour
    positive vs negative drivers.
    """
    feature: str
    weight: float


# WHY: explicit `method` provenance — tests + UI both need to know whether
#      the weights came from .coef_ (LR), .feature_importances_ (XGBoost),
#      or shap.TreeExplainer (Sprint 13, audit C13, opt-in via ML_USE_SHAP).
ExplainMethod = Literal["coef", "feature_importances", "shap", "unsupported"]


class ExplainResponse(BaseModel):
    prob: float | None
    model: str | None
    model_version: str | None
    contributors: list[FeatureContribution]
    method: ExplainMethod
    fallback_reason: FallbackReason | None = None
