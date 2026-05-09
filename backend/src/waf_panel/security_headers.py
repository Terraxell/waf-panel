"""Security-headers middleware — (audit C-list item 15).

WHY: the threat-model named "no security-headers middleware" as a
known gap. This adds the conventional set in one place:

  * Strict-Transport-Security  — enforce HTTPS at the browser level.
  * Content-Security-Policy    — pin sources for scripts/styles/images.
  * X-Frame-Options            — block click-jacking via <iframe>.
  * X-Content-Type-Options     — disable MIME-sniffing.
  * Referrer-Policy            — don't leak panel paths to 3rd parties.
  * Permissions-Policy         — drop access to camera/mic/geo/etc.

SAFETY:
  * The CSP is intentionally conservative: it blocks inline scripts.
    The frontend uses Vite + React — no inline scripts in production
    bundles. If a dev tool needs `'unsafe-inline'`, override via env
    rather than relax the default.
  * HSTS is only emitted when the request actually arrived over TLS;
    browsers ignore it on plain HTTP, but emitting it on a downgrade
    test is misleading. nginx at the edge sets the actual cert/SNI;
    `request.url.scheme` reflects what reached the app.

The middleware is a single ASGI callable so unit tests can hit it
without spinning up uvicorn.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# WHY: live as module-level constants so an env override (.env) can
# replace the value without subclassing the middleware.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "  # CSS-in-JS sometimes needs this
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

DEFAULT_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)

DEFAULT_REFERRER_POLICY = "strict-origin-when-cross-origin"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach the conventional set of hardening headers to every response.

    Configurable so tests can verify each value, and so production can
    relax CSP for a particular deploy without touching the codebase.
    """

    def __init__(
        self,
        app,
        *,
        csp: str = DEFAULT_CSP,
        permissions_policy: str = DEFAULT_PERMISSIONS_POLICY,
        referrer_policy: str = DEFAULT_REFERRER_POLICY,
        hsts_max_age: int = 31_536_000,  # 1 year
        hsts_include_subdomains: bool = True,
    ) -> None:
        super().__init__(app)
        self._csp = csp
        self._perms = permissions_policy
        self._ref = referrer_policy
        self._hsts_max_age = hsts_max_age
        self._hsts_include_subdomains = hsts_include_subdomains

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)

        # WHY: don't smash existing headers — endpoints / static-file
        # responses might set their own (e.g. X-WAF-ML-Prob from Lua).
        response.headers.setdefault("Content-Security-Policy", self._csp)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", self._ref)
        response.headers.setdefault("Permissions-Policy", self._perms)

        # SAFETY: HSTS only over TLS. nginx at the edge handles cert; we
        # check the scheme as the request actually reached the gateway.
        if request.url.scheme == "https":
            value = f"max-age={self._hsts_max_age}"
            if self._hsts_include_subdomains:
                value += "; includeSubDomains"
            response.headers.setdefault("Strict-Transport-Security", value)

        return response


__all__ = [
    "DEFAULT_CSP",
    "DEFAULT_PERMISSIONS_POLICY",
    "DEFAULT_REFERRER_POLICY",
    "SecurityHeadersMiddleware",
]
