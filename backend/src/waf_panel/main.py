"""FastAPI app factory + entry point."""

import logging
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
from .db.session import get_sessionmaker
from .observability import RequestIdMiddleware, install_metrics, setup_structlog
from .repositories.deps import is_in_memory_active
from .repositories.pg import PgUsersRepo
from .security import verify_password
from .security_csrf import CsrfMiddleware
from .security_headers import SecurityHeadersMiddleware

log = logging.getLogger("waf-panel.main")

# Refuse to start in production with a default JWT secret. Dev / test
# stays untouched -- the default secret is fine there.
DEFAULT_JWT_SECRETS = frozenset({
    "dev-secret-do-not-use",
    "change_me_in_a_real_deployment",
    "test-secret-test-secret-test",
})

# WHY hardcode here: the literal "admin" is the documented default in
# the login hint string AND the password for which we hardcoded the
# argon2id seed in alembic migration 0003. Verify against this exact
# string at startup; if it succeeds the operator never rotated.
DEFAULT_ADMIN_PASSWORD = "admin"
DEFAULT_ADMIN_EMAIL = "admin@example.com"


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


def _check_admin_password(
    *,
    waf_env: str,
    in_memory: bool,
    password_hash: str | None,
    is_active: bool,
) -> None:
    """Pure check -- extracted so tests can call it without a real DB.

    Refuses to start when *all* of these are true:
      1. ``WAF_ENV=production``.
      2. We are not in test (in-memory) mode.
      3. An admin row exists.
      4. That admin is active (a disabled admin cannot log in anyway).
      5. The stored hash still verifies the literal string ``"admin"``.

    The check uses ``verify_password`` rather than literal-hash equality
    so a re-hash with a fresh salt (e.g. an operator who ran
    ``hash_password("admin")`` thinking they were rotating) is still
    caught. Argon2 verify is a single ~100 ms call -- fine at boot.
    """
    if waf_env.lower() != "production":
        return
    if in_memory:
        return
    if password_hash is None or not is_active:
        return
    if verify_password(DEFAULT_ADMIN_PASSWORD, password_hash):
        raise RuntimeError(
            f"WAF_ENV=production but the seeded admin user "
            f"({DEFAULT_ADMIN_EMAIL}) still has the default password "
            f"'{DEFAULT_ADMIN_PASSWORD}'. Rotate it before exposing the "
            "panel -- see docs/runbook.md section 8 for the rotation "
            f"steps. Affected account: {DEFAULT_ADMIN_EMAIL}."
        )


async def _validate_admin_password_in_production() -> None:
    """Async wrapper around ``_check_admin_password`` -- looks up the
    admin row in Postgres and runs the guard.

    Skipped in test (in-memory) mode and in any non-production env.
    Defensive against missing rows and DB errors: a brand-new deployment
    where the migration has not run yet should still boot, and any DB
    hiccup at startup should not be a higher bar than the running app
    already imposes.
    """
    settings = get_settings()
    if settings.waf_env.lower() != "production" or is_in_memory_active():
        return

    sm = get_sessionmaker()
    try:
        async with sm() as session:
            repo = PgUsersRepo(session)
            admin = await repo.by_email(DEFAULT_ADMIN_EMAIL)
    except Exception:  # noqa: BLE001
        log.warning(
            "admin-password guard: could not query users table at boot "
            "(probably alembic upgrade has not run yet); skipping check"
        )
        return

    _check_admin_password(
        waf_env=settings.waf_env,
        in_memory=False,
        password_hash=admin.password_hash if admin is not None else None,
        is_active=admin.is_active if admin is not None else False,
    )


@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Runtime guard -- needs DB access, so it cannot sit in the sync
    # _validate_settings. Mirrors the JWT_SECRET guard there in posture.
    await _validate_admin_password_in_production()
    yield
    await dispose_clickhouse()


def create_app() -> FastAPI:
    settings = get_settings()
    _validate_settings(settings)
    setup_structlog(level=settings.log_level)
    app = FastAPI(
        title="waf-panel",
        version=__version__,
        description="Management dashboard for the hybrid WAF (rules + ML).",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=_lifespan,
    )
    # Middleware stack -- Starlette runs these inside-out: the LAST one
    # added runs FIRST on the request, LAST on the response.
    #
    # Order (request flow, top-to-bottom):
    #   1. SecurityHeaders -- adds CSP/HSTS/XFO to every response.
    #   2. CORS            -- preflight handling.
    #   3. CSRF            -- checks X-CSRF-Token vs cookie for mutating
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
    # requests. Bearer-auth flows (CLI/CI) bypass -- see middleware code.
    app.add_middleware(CsrfMiddleware)
    # Outermost layer so the request-id binding wraps every other
    # middleware's logs (CORS, CSRF, SecurityHeaders all emit through
    # stdlib logging which structlog now formats).
    app.add_middleware(RequestIdMiddleware)

    # Prometheus /metrics -- registered before routers so the route
    # ordering is deterministic. Excluded from OpenAPI on purpose
    # (it's an ops surface, not part of the SPA contract).
    install_metrics(app)

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
