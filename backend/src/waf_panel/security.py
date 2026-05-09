"""Auth primitives: password hashing + JWT issue/verify.

WHY: kept tiny on purpose. Anything fancier (refresh tokens, MFA, SSO) is a
     Sprint-9 problem, and adding it now would mean code we throw away when
     the design changes.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import get_settings

# WHY: `datetime.UTC` is Python 3.11+; we still want to support the 3.10 sandbox.
UTC = timezone.utc

# NOTE: argon2id by default; bcrypt left available for legacy hashes.
_pwd = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except ValueError:
        # WHY: passlib raises on garbage hashes; we treat them as a failed
        #      verification rather than crashing the request.
        return False


def issue_access_token(
    subject: str,
    role: str,
    *,
    email: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    if email is not None:
        payload["email"] = email
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Return the verified payload, or raise jose.JWTError on failure."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


__all__ = [
    "JWTError",
    "decode_access_token",
    "hash_password",
    "issue_access_token",
    "verify_password",
]
