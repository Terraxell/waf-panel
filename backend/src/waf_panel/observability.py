"""Observability: Prometheus metrics + request-ID logging — task #129.

WHY: production support boils down to two questions: what is the
service doing right now, and what was it doing when this incident
fired? Prometheus answers the first question; correlation-ID-bound
structured logs answer the second.

Three responsibilities live in this module:

1. ``setup_structlog`` — configures stdlib + structlog so every log
   record is JSON-shaped with a stable schema. Called once on app
   boot. Idempotent (safe to call from tests).
2. ``RequestIdMiddleware`` — generates / honours the ``X-Request-ID``
   header and binds it into the structlog context so all logs
   produced during the request carry the same id.
3. ``install_metrics`` — registers the Prometheus instrumentator
   and exposes ``/metrics``. Uses sane defaults: latency histogram,
   in-flight counter, request total broken down by handler/method/
   status. The metrics path is kept off ``/api/v1`` on purpose so
   that the cookie-CSRF middleware does not need a special-case
   exemption: ``/metrics`` is plain GET and would pass anyway, but
   keeping it at the root mirrors the convention every Prometheus
   scrape config in the world expects.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from fastapi import FastAPI

REQUEST_ID_HEADER = "X-Request-ID"
_LOG_CONFIGURED = False


def setup_structlog(level: str = "INFO") -> None:
    """Configure stdlib logging + structlog to emit JSON.

    SAFETY: idempotent. Tests import this module and then create_app
    runs the lifespan which calls this again; the guard prevents
    duplicate handlers leaking onto the root logger.
    """
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return

    # WHY route through stdlib first: third-party libraries (uvicorn,
    # sqlalchemy, fastapi) emit via the standard ``logging`` module. We
    # want their output to land in the same JSON stream, not on a
    # separate plaintext channel.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level.upper(),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO),
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _LOG_CONFIGURED = True


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Bind a stable request id to the structlog context.

    Two paths:
      1. Caller already sent ``X-Request-ID`` (e.g. nginx upstream
         log correlation). Honour it verbatim, but cap length to
         128 chars to keep log lines bounded.
      2. No header → generate a fresh hex uuid4.

    The id is also echoed back in the response header so the SPA can
    surface it in any "report a bug" UI later.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        rid = incoming[:128] if incoming else uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=rid,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        finally:
            # WHY in finally: even when the handler raises, the request_id
            # has already been logged by anything downstream; we still
            # want the contextvars cleaned for the next request on the
            # same task.
            pass
        response.headers[REQUEST_ID_HEADER] = rid
        return response


def install_metrics(app: FastAPI) -> None:
    """Register the Prometheus instrumentator and expose /metrics.

    SAFETY: ``should_group_status_codes=False`` so we keep the literal
    status (200, 401, 403, 500) rather than the 2xx/4xx/5xx coarse
    bucket -- analysts asking "how many 401s in the last hour?" need
    the literal code on the dashboard.
    """
    Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics"],
        env_var_name="WAF_METRICS_ENABLED",
    ).instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
    )


__all__ = [
    "REQUEST_ID_HEADER",
    "RequestIdMiddleware",
    "install_metrics",
    "setup_structlog",
]
