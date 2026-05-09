"""Auth endpoints — DB-backed via repositories and AuthService.

Cookie + CSRF auth (ADR-0014): /login plants both the session cookie
(httpOnly) and the CSRF token cookie (JS-readable) so the browser SPA
can authenticate without storing the JWT in JS memory. CLI / CI keep
using ``Authorization: Bearer ...`` -- both paths converge in
``current_user`` below.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer

from ..config import get_settings
from ..repositories.deps import AuditRepoDep, UsersRepoDep
from ..schemas import CsrfOut, CurrentUser, LoginIn, TokenOut
from ..security import JWTError, decode_access_token
from ..security_csrf import (
    clear_session_cookies,
    generate_csrf_token,
    set_session_cookies,
)
from ..security_rate_limit import check_login_rate
from ..services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

# auto_error=False so OAuth2PasswordBearer doesn't 401 when the
# Authorization header is absent -- the request might still authenticate
# via the session cookie. We do the actual rejection in current_user.
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _client_ip(request: Request) -> str:
    """Best-effort client IP -- honours X-Forwarded-For when behind nginx."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@router.post("/login", response_model=TokenOut)
async def login(
    payload: LoginIn,
    users: UsersRepoDep,
    audit: AuditRepoDep,
    request: Request,
    response: Response,
) -> TokenOut:
    if not check_login_rate(ip=_client_ip(request), email=str(payload.email)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many login attempts, try again in a minute",
        )

    settings = get_settings()
    service = AuthService(users=users, audit=audit, ttl_minutes=settings.jwt_ttl_minutes)
    try:
        bundle = await service.login(email=str(payload.email), password=payload.password)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    csrf = set_session_cookies(
        response,
        request=request,
        jwt=bundle.access_token,
        ttl_seconds=bundle.expires_in,
    )

    return TokenOut(
        access_token=bundle.access_token,
        expires_in=bundle.expires_in,
        csrf_token=csrf,
    )


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Clear the session + CSRF cookies. 200 with no body on success.

    WHY 200 not 204: Starlette strips Set-Cookie on 204. 200 with
    empty body is functionally equivalent and preserves the cookies.
    """
    out = Response(status_code=200, content=b"")
    clear_session_cookies(out, request=request)
    return out


@router.get("/csrf", response_model=CsrfOut)
async def csrf(request: Request, response: Response) -> CsrfOut:
    """Refresh the CSRF token while the session cookie is still valid."""
    settings = get_settings()
    jwt = request.cookies.get(settings.cookie_session_name)
    if not jwt:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    try:
        decode_access_token(jwt)
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired") from exc

    fresh = generate_csrf_token()
    set_session_cookies(
        response,
        request=request,
        jwt=jwt,
        ttl_seconds=settings.jwt_ttl_minutes * 60,
        csrf_token=fresh,
    )
    return CsrfOut(csrf_token=fresh)


async def current_user(
    request: Request,
    bearer: Annotated[str | None, Depends(oauth2)] = None,
) -> CurrentUser:
    """Resolve the caller from cookie or Bearer header.

    Lookup order:
      1. ``Authorization: Bearer ...`` -- explicit, CLI/CI/script flow.
      2. ``waf_session`` cookie -- browser flow.
    """
    settings = get_settings()
    token = bearer or request.cookies.get(settings.cookie_session_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    try:
        claims = decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
    return CurrentUser(
        id=UUID(claims["sub"]),
        email=claims.get("email", "unknown@example.com"),
        role=claims["role"],
        is_active=True,
    )


@router.get("/me", response_model=CurrentUser)
async def me(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    return user


def require_role(*allowed: str):
    async def _check(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user
    return _check


__all__ = ["current_user", "require_role", "router"]
