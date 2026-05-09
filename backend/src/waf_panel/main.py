"""FastAPI app factory + entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import audit as audit_api
from .api import auth as auth_api
from .api import drift as drift_api
from .api import health as health_api
from .api import incidents as incidents_api
from .api import metrics as metrics_api
from .api import ml as ml_api
from .api import rules as rules_api
from .clickhouse_client import dispose_clickhouse
from .config import Settings, get_settings
from .security_csrf import CsrfMiddleware
from .security_headers import SecurityHeadersMiddleware

# Refuse to start in production with a default JWT secret. Dev / test
# stays untouched — the default secret is fine there.
DEFAULT_JWT_SECRETS = frozenset({
    "dev-secret-do-not-use",
    "change_me_in_a_real_deployment",
    "test-secret-test-secret-test",
})


def _validate_settings(settings: Settings) -> None:
    """Hard-fail on startup when production config is unsafe."""
    if settings.waf_env.lower() != "production":
        return
    if settings.jwt_secret in DEFAULT_JWT_SECRETS:
        raise RuntimeError(
            "WAF_ENV=production but JWT_SECRET is a known default. "
            "Generate a fresh secret (openssl rand -hex 32) and set "
            "JWT_SECRET in the deployment environment."
        )
    if len(settings.jwt_secret) < 32:
        raise RuntimeError(
            "WAF_ENV=production but JWT_SECRET is < 32 chars. "
            "Use at least 32 hex chars (openssl rand -hex 32)."
        )


@asynccontextmanager
async def _lifespan(_: FastAPI):
    yield
    await dispose_clickhouse()


def create_app() -> FastAPI:
    settings = get_settings()
    _validate_settings(settings)
    app = FastAPI(
        title="waf-panel",
        version=__version__,
        description="Management dashboard for the hybrid WAF (rules + ML).",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=_lifespan,
    )
    # Middleware stack — Starlette runs these inside-out: the LAST one
    # added runs FIRST on the request, LAST on the response.
    #
    # Order (request flow, top-to-bottom):
    #   1. SecurityHeaders — adds CSP/HSTS/XFO to every response.
    #   2. CORS            — preflight handling.
    #   3. CSRF            — checks X-CSRF-Token vs cookie for mutating
    #                         requests. Skipped for safe methods, login,
    #                         logout, and Bearer-auth calls.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # ADR-0014: double-submit CSRF for cookie-authenticated mutating
    # requests. Bearer-auth flows (CLI/CI) bypass — see middleware code.
    app.add_middleware(CsrfMiddleware)

    app.include_router(health_api.router)
    app.include_router(auth_api.router, prefix="/api/v1")
    app.include_router(rules_api.router, prefix="/api/v1")
    app.include_router(metrics_api.router, prefix="/api/v1")
    app.include_router(incidents_api.router, prefix="/api/v1")
    app.include_router(audit_api.router, prefix="/api/v1")
    app.include_router(drift_api.router, prefix="/api/v1")
    app.include_router(ml_api.router, prefix="/api/v1")

    return app


app = create_app()
