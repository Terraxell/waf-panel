"""FastAPI app — POST /score, POST /explain, GET /healthz, GET /readyz."""

from __future__ import annotations

import logging
import math
import time
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI

from . import __version__
from .cache import ScoreCache, cache_key, make_cache
from .config import Settings, get_settings
from .model_loader import LoadedModel, load_active_model
from .schemas import (
    ExplainResponse,
    FeatureContribution,
    HealthResponse,
    ScoreRequest,
    ScoreResponse,
)

log = logging.getLogger("waf-ml-service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class _AppState:
    """A stateful holder so tests can inject a pre-built model/cache."""

    settings: Settings
    model: LoadedModel | None
    cache: ScoreCache

    def __init__(self) -> None:
        self.settings = get_settings()
        self.model = None
        self.cache = ScoreCache(client=None, ttl_sec=30)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    state: _AppState = app.state.bag  # type: ignore[attr-defined]
    state.model = load_active_model(state.settings)
    state.cache = make_cache(state.settings.redis_url, state.settings.redis_ttl_sec)
    if state.model is not None:
        log.info(
            "model loaded: algo=%s version=%s source=%s",
            state.model.algo, state.model.version, state.model.source,
        )
    else:
        log.warning("no model loaded — /score will return fallback responses")
    yield


def create_app(state: _AppState | None = None) -> FastAPI:
    state = state or _AppState()
    app = FastAPI(
        title="waf-ml-service",
        version=__version__,
        description="Online ML inference for the WAF dashboard.",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )
    app.state.bag = state  # type: ignore[attr-defined]

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        s: _AppState = app.state.bag
        return HealthResponse(
            status="ok" if s.model is not None else "degraded",
            model_loaded=s.model is not None,
            model_version=s.model.version if s.model else None,
            redis_ok=s.cache.healthy,
        )

    @app.get("/readyz", response_model=HealthResponse)
    def readyz() -> HealthResponse:
        return healthz()

    @app.post("/score", response_model=ScoreResponse)
    def score(req: ScoreRequest) -> ScoreResponse:
        return _score_request(app.state.bag, req)

    @app.post("/explain", response_model=ExplainResponse)
    def explain(req: ScoreRequest, top_k: int = 5) -> ExplainResponse:
        return _explain_request(app.state.bag, req, top_k=top_k)

    return app


def _featurize(req: ScoreRequest) -> np.ndarray:
    from waf_ml.features import FEATURE_COLUMNS, featurize

    feats = featurize({
        "method": req.method,
        "path": req.path,
        "query": req.query,
        "body": req.body,
        "user_agent": req.user_agent,
        "referer": req.referer,
        "headers": req.headers,
    })
    vec = np.asarray([feats[c] for c in FEATURE_COLUMNS], dtype=np.float64)
    return vec.reshape(1, -1)


def _model_prob(estimator: Any, X: np.ndarray) -> float:
    if hasattr(estimator, "predict_proba"):
        return float(estimator.predict_proba(X)[0, 1])
    if hasattr(estimator, "decision_function"):
        # fix: was per-batch min/max normalisation, which
        # collapsed to 0 on batch=1 (online inference). Now we use a
        # stable sigmoid centred at decision_function=0:
        #   IsolationForest's decision_function: ≥ 0 = inlier, < 0 = anomaly.
        #   prob_attack = 1 / (1 + e^(scale * df))
        # `scale=4` is a calibration constant chosen so df=±0.25 maps to
        # ≈0.27/0.73; per-model calibration lives in this release if needed.
        df = float(estimator.decision_function(X)[0])
        scale = 4.0
        return 1.0 / (1.0 + math.exp(scale * df))
    raise AttributeError("estimator has neither predict_proba nor decision_function")


def _score_request(state: _AppState, req: ScoreRequest) -> ScoreResponse:
    started = time.perf_counter()

    if state.model is None:
        return ScoreResponse(
            prob=None, model=None, model_version=None,
            latency_ms=0.0, cached=False,
            fallback_reason="no_active_model",
        )

    key = cache_key(req.method, req.path, req.query)
    hit = state.cache.get(key)
    if hit is not None:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return ScoreResponse(
            prob=hit.get("prob"),
            model=hit.get("model"),
            model_version=hit.get("model_version"),
            latency_ms=round(elapsed_ms, 3),
            cached=True,
        )

    try:
        X = _featurize(req)
    except Exception as e:  # noqa: BLE001
        log.error("featurize failed: %s", e)
        return ScoreResponse(
            prob=None, model=state.model.algo, model_version=state.model.version,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            cached=False, fallback_reason="feature_error",
        )

    try:
        prob = _model_prob(state.model.estimator, X)
    except Exception as e:  # noqa: BLE001
        log.error("predict failed: %s", e)
        return ScoreResponse(
            prob=None, model=state.model.algo, model_version=state.model.version,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            cached=False, fallback_reason="predict_error",
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    payload = {
        "prob": prob,
        "model": state.model.algo,
        "model_version": state.model.version,
    }
    state.cache.set(key, payload)

    return ScoreResponse(
        prob=prob,
        model=state.model.algo,
        model_version=state.model.version,
        latency_ms=round(elapsed_ms, 3),
        cached=False,
    )


def _model_weights(estimator: Any) -> tuple[np.ndarray | None, str]:
    coef = getattr(estimator, "coef_", None)
    if coef is not None:
        arr = np.asarray(coef).reshape(-1)
        return arr, "coef"
    fi = getattr(estimator, "feature_importances_", None)
    if fi is not None:
        return np.asarray(fi).reshape(-1), "feature_importances"
    return None, "unsupported"


def _explain_request(
    state: _AppState, req: ScoreRequest, *, top_k: int = 5,
) -> ExplainResponse:
    if state.model is None:
        return ExplainResponse(
            prob=None, model=None, model_version=None,
            contributors=[], method="unsupported",
            fallback_reason="no_active_model",
        )

    try:
        from waf_ml.features import FEATURE_COLUMNS

        X = _featurize(req)
    except Exception as e:  # noqa: BLE001
        log.error("featurize failed in /explain: %s", e)
        return ExplainResponse(
            prob=None, model=state.model.algo, model_version=state.model.version,
            contributors=[], method="unsupported",
            fallback_reason="feature_error",
        )

    try:
        prob = _model_prob(state.model.estimator, X)
    except Exception as e:  # noqa: BLE001
        log.error("predict failed in /explain: %s", e)
        prob = None

    # (audit C13): if the operator opted in via ML_USE_SHAP=true,
    # try TreeSHAP first. It returns per-feature contributions directly
    # (no weights×feature multiplication needed). On any failure (shap
    # not installed, non-tree model, runtime error) we fall through to
    # the legacy linear path below — single source of truth.
    method: str
    contributions: np.ndarray | None = None
    if state.settings.use_shap:
        from . import shap_explainer

        sv = shap_explainer.shap_contributions(state.model.estimator, X)
        if sv is not None and sv.size == len(FEATURE_COLUMNS):
            contributions = sv
            method = "shap"

    if contributions is None:
        weights, method = _model_weights(state.model.estimator)
        if weights is None:
            return ExplainResponse(
                prob=prob, model=state.model.algo, model_version=state.model.version,
                contributors=[], method="unsupported",
            )
        feat_vec = X.reshape(-1)
        contributions = weights * feat_vec

    if contributions.size != len(FEATURE_COLUMNS):
        return ExplainResponse(
            prob=prob, model=state.model.algo, model_version=state.model.version,
            contributors=[], method="unsupported",
            fallback_reason="feature_error",
        )

    abs_contrib = np.abs(contributions)
    if abs_contrib.sum() <= 1e-12:
        return ExplainResponse(
            prob=prob, model=state.model.algo, model_version=state.model.version,
            contributors=[], method=method,
        )
    order = np.argsort(-abs_contrib)[: max(1, int(top_k))]
    chosen_abs = abs_contrib[order]
    norm = chosen_abs / chosen_abs.sum()
    contributors = [
        FeatureContribution(
            feature=FEATURE_COLUMNS[i],
            weight=float(norm[k] if contributions[i] >= 0 else -norm[k]),
        )
        for k, i in enumerate(order)
    ]

    return ExplainResponse(
        prob=prob,
        model=state.model.algo,
        model_version=state.model.version,
        contributors=contributors,
        method=method,
    )


# Top-level instance for `uvicorn waf_ml_service.main:app`.
app = create_app()
