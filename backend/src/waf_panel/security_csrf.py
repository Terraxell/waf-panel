"""Cookie-based session + double-submit CSRF — see ADR-0014.

Three exports:

1. ``set_session_cookies`` — called from ``/auth/login`` to plant the
   pair of cookies on the browser.
2. ``clear_session_cookies`` — called from ``/auth/logout``.
3. ``CsrfMiddleware`` — Starlette middleware that fails any mutating
   request whose ``X-CSRF-Token`` header doesn't match the
   ``waf_csrf`` cookie. Bearer-authenticated requests bypass.
"""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import get_settings

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def generate_csrf_token() -> str:
    """32 bytes of OS randomness, URL-safe base64."""
    return secrets.token_urlsafe(32)


def set_session_cookies(
    response: Response,
    *,
    request: Request,
    jwt: str,
    ttl_seconds: int,
    csrf_token: str | None = None,
) -> str:
    """Plant session + CSRF cookies. Returns the CSRF token used."""
    settings = get_settings()
    secure = request.url.scheme == "https"
    csrf = csrf_token or generate_csrf_token()

    response.set_cookie(
        key=settings.cookie_session_name,
        value=jwt,
        max_age=ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        key=settings.cookie_csrf_name,
        value=csrf,
        max_age=ttl_seconds,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )
    return csrf


def clear_session_cookies(response: Response, *, request: Request) -> None:
    """Tell the browser to delete both cookies."""
    settings = get_settings()
    secure = request.url.scheme == "https"
    for name in (settings.cookie_session_name, settings.cookie_csrf_name):
        response.set_cookie(
            key=name,
            value="",
            max_age=0,
            httponly=(name == settings.cookie_session_name),
            secure=secure,
            samesite="strict",
            path="/",
        )


class CsrfMiddleware(BaseHTTPMiddleware):
    """Reject mutating requests without a matching CSRF header.

    Skip rules (in order):
      1. Safe methods (GET/HEAD/OPTIONS) — never mutate.
      2. Login/logout — chicken-and-egg.
      3. ``Authorization: Bearer ...`` — explicit credential, CLI/CI.
      4. No session cookie present — no implicit credential, no CSRF
         risk. Downstream auth handles the 401.
    """

    _CSRF_EXEMPT_PATHS = ("/api/v1/auth/login", "/api/v1/auth/logout")

    async def dispatch(self, request: Request, call_next):
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        if any(request.url.path.startswith(p) for p in self._CSRF_EXEMPT_PATHS):
            return await call_next(request)

        auth_hdr = request.headers.get("authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            return await call_next(request)

        settings = get_settings()

        # No session cookie → no implicit credential to abuse, so CSRF
        # is moot. Pass through; the auth dependency will return 401.
        if not request.cookies.get(settings.cookie_session_name):
            return await call_next(request)

        cookie_value = request.cookies.get(settings.cookie_csrf_name)
        header_value = request.headers.get("x-csrf-token")

        if not cookie_value or not header_value or cookie_value != header_value:
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing or invalid"},
            )

        return await call_next(request)


__all__ = [
    "CsrfMiddleware",
    "clear_session_cookies",
    "generate_csrf_token",
    "set_session_cookies",
]
