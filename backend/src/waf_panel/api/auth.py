"""Auth endpoints — ADR-0014 cookie+CSRF + ADR-0015 refresh rotation.

POST /auth/login    issue access (15 min) + refresh (14 d) cookies
POST /auth/logout   revoke family + clear cookies
GET  /auth/csrf     refresh CSRF token while session valid
GET  /auth/me       resolve caller (cookie or Bearer)
POST /auth/refresh  rotate the refresh family + issue new access
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError as JoseJWTError

from ..config import get_settings
from ..repositories.deps import (
    AuditRepoDep,
    RefreshFamiliesRepoDep,
    UsersRepoDep,
)
from ..schemas import CsrfOut, CurrentUser, LoginIn, TokenOut
from ..security import JWTError, decode_access_token, issue_access_token
from ..security_csrf import (
    clear_refresh_cookie,
    clear_session_cookies,
    generate_csrf_token,
    set_refresh_cookie,
    set_session_cookies,
)
from ..security_rate_limit import check_login_rate
from ..security_refresh import (
    REFRESH_TTL_DAYS,
    RefreshVerdict,
    decode_refresh_token,
    evaluate_replay,
    issue_refresh_token,
)
from ..services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _refresh_ttl_seconds() -> int:
    return REFRESH_TTL_DAYS * 24 * 60 * 60


@router.post("/login", response_model=TokenOut)
async def login(
    payload: LoginIn,
    users: UsersRepoDep,
    audit: AuditRepoDep,
    refresh_repo: RefreshFamiliesRepoDep,
    request: Request,
    response: Response,
) -> TokenOut:
    if not check_login_rate(ip=_client_ip(request), email=str(payload.email)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many login attempts, try again in a minute",
        )

    settings = get_settings()
    # ADR-0015: AuthService still issues the legacy long-lived access
    # for `Authorization: Bearer ...` callers. The browser path uses
    # access_ttl_minutes (short) and refreshes via /auth/refresh.
    service = AuthService(users=users, audit=audit, ttl_minutes=settings.access_ttl_minutes)
    try:
        bundle = await service.login(email=str(payload.email), password=payload.password)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    # Plant the access + CSRF cookies (ADR-0014).
    csrf = set_session_cookies(
        response,
        request=request,
        jwt=bundle.access_token,
        ttl_seconds=bundle.expires_in,
    )

    # ADR-0015: spin up a fresh refresh family, generation 0, plant the
    # refresh cookie scoped to /api/v1/auth/.
    family = await refresh_repo.create(user_id=bundle.user_id)
    refresh_jwt = issue_refresh_token(
        user_id=bundle.user_id,
        family_id=family.id,
        generation=family.generation,
    )
    set_refresh_cookie(
        response,
        request=request,
        token=refresh_jwt,
        ttl_seconds=_refresh_ttl_seconds(),
    )

    return TokenOut(
        access_token=bundle.access_token,
        expires_in=bundle.expires_in,
        csrf_token=csrf,
    )


@router.post("/logout")
async def logout(
    request: Request,
    audit: AuditRepoDep,
    refresh_repo: RefreshFamiliesRepoDep,
) -> Response:
    """Revoke the refresh family + clear both cookies. 200 with empty body."""
    settings = get_settings()
    out = Response(status_code=200, content=b"")
    clear_session_cookies(out, request=request)
    clear_refresh_cookie(out, request=request)

    # Best-effort family revoke. Decode failures are not a logout failure
    # -- if the cookie is gone or garbled, the cookies are still cleared.
    refresh_jwt = request.cookies.get(settings.cookie_refresh_name, "")
    if refresh_jwt:
        try:
            claims = decode_refresh_token(refresh_jwt)
        except JoseJWTError:
            return out
        await refresh_repo.revoke(claims.family_id)
        await audit.record(
            actor_id=claims.user_id,
            action="auth.logout",
            target=str(claims.family_id),
            payload={},
        )
    return out


@router.get("/csrf", response_model=CsrfOut)
async def csrf(request: Request, response: Response) -> CsrfOut:
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
        ttl_seconds=settings.access_ttl_minutes * 60,
        csrf_token=fresh,
    )
    return CsrfOut(csrf_token=fresh)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    request: Request,
    response: Response,
    users: UsersRepoDep,
    audit: AuditRepoDep,
    refresh_repo: RefreshFamiliesRepoDep,
) -> TokenOut:
    """ADR-0015 rotation endpoint. Returns a new access + sets a new
    refresh cookie. On replay (older generation than DB) revokes the
    family and 401s both parties on next call.
    """
    settings = get_settings()
    refresh_jwt = request.cookies.get(settings.cookie_refresh_name, "")
    if not refresh_jwt:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no refresh cookie")
    try:
        claims = decode_refresh_token(refresh_jwt)
    except JoseJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh") from exc

    family = await refresh_repo.by_id(claims.family_id)
    family_gen = family.generation if family is not None else None
    family_revoked = bool(family is not None and family.revoked_at is not None)

    verdict = evaluate_replay(
        presented=claims,
        family_generation=family_gen,
        family_revoked=family_revoked,
    )
    if verdict == RefreshVerdict.REJECT:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh rejected")
    if verdict == RefreshVerdict.REVOKE:
        await refresh_repo.revoke(claims.family_id)
        await audit.record(
            actor_id=claims.user_id,
            action="auth.refresh.replay_revoked",
            target=str(claims.family_id),
            payload={
                "presented_generation": claims.generation,
                "expected_generation": family_gen,
            },
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh replay; family revoked")

    # ROTATE -- bump generation atomically.
    updated = await refresh_repo.bump_generation(claims.family_id)
    if updated is None:
        # Race: family was revoked between by_id() and bump_generation().
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "family revoked mid-rotation")

    user = await users.by_id(claims.user_id)
    if user is None or not user.is_active:
        # User deleted / disabled since the family was created.
        await refresh_repo.revoke(claims.family_id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer active")

    new_access = issue_access_token(
        subject=str(user.id),
        role=user.role,
        email=user.email,
    )
    new_refresh = issue_refresh_token(
        user_id=user.id,
        family_id=updated.id,
        generation=updated.generation,
    )
    csrf_value = set_session_cookies(
        response,
        request=request,
        jwt=new_access,
        ttl_seconds=settings.access_ttl_minutes * 60,
    )
    set_refresh_cookie(
        response,
        request=request,
        token=new_refresh,
        ttl_seconds=_refresh_ttl_seconds(),
    )
    return TokenOut(
        access_token=new_access,
        expires_in=settings.access_ttl_minutes * 60,
        csrf_token=csrf_value,
    )


async def current_user(
    request: Request,
    bearer: Annotated[str | None, Depends(oauth2)] = None,
) -> CurrentUser:
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
