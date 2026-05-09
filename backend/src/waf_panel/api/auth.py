"""Auth endpoints — DB-backed via repositories and AuthService."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from ..config import get_settings
from ..repositories.deps import AuditRepoDep, UsersRepoDep
from ..schemas import CurrentUser, LoginIn, TokenOut
from ..security import JWTError, decode_access_token
from ..security_rate_limit import check_login_rate
from ..services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def _client_ip(request: Request) -> str:
    """Best-effort client IP — honours X-Forwarded-For when behind nginx."""
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
) -> TokenOut:
    # Sprint 11 hotfix: 5 attempts per (ip, email) per 60 s.
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
    return TokenOut(access_token=bundle.access_token, expires_in=bundle.expires_in)


async def current_user(
    token: Annotated[str, Depends(oauth2)],
) -> CurrentUser:
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
