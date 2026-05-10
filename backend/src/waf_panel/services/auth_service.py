"""Authentication service.

Encapsulates: lookup → password verification → token issue → audit row.
The HTTP layer stays a thin shell that maps service results to status codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..repositories.base import AuditRepo, UsersRepo
from ..security import issue_access_token, verify_password


class AuthError(Exception):
    """Raised on any auth failure. Always presented as HTTP 401."""


@dataclass
class TokenBundle:
    access_token: str
    expires_in: int
    # ADR-0015: api/auth.py needs the user identity to spin up a
    # refresh family right after AuthService.login returns OK. Adding
    # the fields here saves one DB round-trip in the login handler.
    user_id: UUID
    role: str
    email: str


class AuthService:
    def __init__(self, users: UsersRepo, audit: AuditRepo, ttl_minutes: int) -> None:
        self._users = users
        self._audit = audit
        self._ttl_minutes = ttl_minutes

    async def login(self, *, email: str, password: str) -> TokenBundle:
        user = await self._users.by_email(email)
        if user is None or not user.is_active:
            # WHY: same error for "no such user" and "inactive" so we don't leak
            #      account existence to the caller.
            raise AuthError("invalid credentials")
        if not verify_password(password, user.password_hash):
            await self._audit.record(
                actor_id=None,
                action="auth.login.failed",
                target=f"users:{user.id}",
                payload={"email": email},
            )
            raise AuthError("invalid credentials")

        await self._users.touch_login(user.id)
        await self._audit.record(
            actor_id=user.id,
            action="auth.login.ok",
            target=f"users:{user.id}",
            payload={"email": email},
        )
        # WHY: include email in the JWT so /auth/me can return the human-readable
        #      identifier without an extra DB round-trip per request.
        token = issue_access_token(
            subject=str(user.id),
            role=user.role,
            email=user.email,
        )
        return TokenBundle(
            access_token=token,
            expires_in=self._ttl_minutes * 60,
            user_id=user.id,
            role=user.role,
            email=user.email,
        )


__all__ = ["AuthError", "AuthService", "TokenBundle"]
