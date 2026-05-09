"""Refresh-token rotation primitives — ADR-0015.

Three pure helpers + one orchestrator function that takes the
"current family state from DB, JWT claims of the presented refresh"
and returns a verdict: ROTATE (issue new pair, bump generation),
REVOKE (theft detected, revoke family), or REJECT (already revoked
or expired).

WHY pure: the auth router calls these and decides what to do with
the verdict (write to DB, set cookies, audit). Pulling the policy
out of the endpoint makes it cheap to test every replay scenario
without spinning up FastAPI.

Refresh token JWT shape:
    {
        "sub": "<user-id-uuid>",
        "family_id": "<family-uuid>",
        "generation": <int>,
        "iat": <unix-ts>,
        "exp": <unix-ts>,
        "type": "refresh"
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from .config import get_settings

UTC = timezone.utc

# WHY 14 days: long enough that a daily-active user never re-auths
# unless they actively log out, short enough that a stolen refresh
# stops working in two weeks worst-case.
REFRESH_TTL_DAYS = 14
REFRESH_TYPE = "refresh"


class RefreshVerdict(str, Enum):  # noqa: UP042 -- StrEnum is 3.11+; keep 3.10 compat for local dev sandbox
    """What the auth router should do with a presented refresh."""
    ROTATE = "rotate"   # OK — bump generation, issue new pair
    REVOKE = "revoke"   # replay/theft detected — revoke family
    REJECT = "reject"   # already revoked or invalid — 401, no DB change


@dataclass
class RefreshClaims:
    user_id: UUID
    family_id: UUID
    generation: int


def issue_refresh_token(
    *, user_id: UUID, family_id: UUID, generation: int,
) -> str:
    """Encode a refresh JWT with the family + generation pair.

    Uses the same signing secret as access tokens (jwt_secret). A
    real production deploy might want a separate refresh_secret so
    a leaked access secret doesn't compromise refresh; left as a
    follow-up because for this project the single secret matches
    ADR-0014's posture.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "family_id": str(family_id),
        "generation": int(generation),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=REFRESH_TTL_DAYS)).timestamp()),
        "type": REFRESH_TYPE,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_refresh_token(token: str) -> RefreshClaims:
    """Verify signature + ``type=refresh`` claim. Raises JWTError on
    any failure (caller maps to 401)."""
    settings = get_settings()
    raw = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if raw.get("type") != REFRESH_TYPE:
        # Reject access tokens presented at /auth/refresh.
        raise JWTError("not a refresh token")
    try:
        return RefreshClaims(
            user_id=UUID(raw["sub"]),
            family_id=UUID(raw["family_id"]),
            generation=int(raw["generation"]),
        )
    except (KeyError, ValueError) as e:
        raise JWTError(f"malformed refresh claims: {e}") from e


def evaluate_replay(
    *,
    presented: RefreshClaims,
    family_generation: int | None,
    family_revoked: bool,
) -> RefreshVerdict:
    """Pure decision tree. Pass current DB state of the family + the
    decoded claim; get back what to do.

    SAFETY: family_generation=None means the family doesn't exist in
    the DB — treat as REJECT (forged or revoked-and-cleaned-up).
    """
    if family_generation is None or family_revoked:
        return RefreshVerdict.REJECT
    if presented.generation > family_generation:
        # Token claims to be NEWER than what the DB has -- forged.
        # We never issued a generation higher than the current one.
        return RefreshVerdict.REJECT
    if presented.generation < family_generation:
        # The presented token is older than the latest. Either the
        # client is offline-replaying (browser tab from yesterday) or
        # the token was stolen and the legit user already rotated.
        # Either way: revoke the family. Bouncing a confused tab is
        # cheap; tolerating a stolen-token attacker is expensive.
        return RefreshVerdict.REVOKE
    # presented.generation == family_generation: legitimate rotation.
    return RefreshVerdict.ROTATE


__all__ = [
    "REFRESH_TTL_DAYS",
    "REFRESH_TYPE",
    "RefreshClaims",
    "RefreshVerdict",
    "decode_refresh_token",
    "evaluate_replay",
    "issue_refresh_token",
]
