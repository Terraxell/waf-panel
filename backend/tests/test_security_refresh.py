"""Refresh-token rotation primitives — ADR-0015.

Six behaviours we lock down:

1. Encode round-trips: a token I issue verifies to the same claims.
2. ``type=access`` is rejected at decode_refresh_token (no
   confusion between access JWTs and refresh JWTs).
3. evaluate_replay returns ROTATE on the legitimate path
   (presented.generation == family_generation).
4. evaluate_replay returns REVOKE when the presented generation is
   OLDER than the DB. This is the theft-detection signal.
5. evaluate_replay returns REJECT when the family was already
   revoked (replay after theft response).
6. evaluate_replay returns REJECT when the family doesn't exist
   (forged token with random family_id, or family deleted).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from jose import JWTError

# WHY: jwt secret must be set BEFORE waf_panel.config is first imported.
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test")

from waf_panel.security_refresh import (  # noqa: E402, I001  -- env above
    REFRESH_TYPE,
    RefreshClaims,
    RefreshVerdict,
    decode_refresh_token,
    evaluate_replay,
    issue_refresh_token,
)
from waf_panel.security import issue_access_token  # noqa: E402, I001


# ── 1. Encode/decode round-trip ─────────────────────────────────────


def test_issue_then_decode_roundtrips():
    user_id = uuid4()
    family_id = uuid4()
    token = issue_refresh_token(user_id=user_id, family_id=family_id, generation=3)
    claims = decode_refresh_token(token)
    assert claims.user_id == user_id
    assert claims.family_id == family_id
    assert claims.generation == 3


# ── 2. Access tokens are rejected ───────────────────────────────────


def test_access_token_rejected_at_refresh_decode():
    """An attacker who can read waf_session might try to present it
    at /auth/refresh. The 'type' claim discriminates."""
    access = issue_access_token(str(uuid4()), role="admin")
    with pytest.raises(JWTError, match="not a refresh"):
        decode_refresh_token(access)


def test_garbled_refresh_rejected():
    with pytest.raises(JWTError):
        decode_refresh_token("totally-not-a-jwt")


# ── 3. Happy-path rotation ──────────────────────────────────────────


def test_evaluate_replay_rotates_on_matching_generation():
    presented = RefreshClaims(
        user_id=uuid4(), family_id=uuid4(), generation=5,
    )
    verdict = evaluate_replay(
        presented=presented,
        family_generation=5,
        family_revoked=False,
    )
    assert verdict == RefreshVerdict.ROTATE


# ── 4. Replay = REVOKE ──────────────────────────────────────────────


def test_evaluate_replay_revokes_on_older_generation():
    """The whole point of rotation: an older-generation refresh
    means someone (the legit user OR an attacker) already rotated.
    Whichever came second is presenting a stale token. Defence:
    revoke the family, both parties get bounced to /login."""
    presented = RefreshClaims(
        user_id=uuid4(), family_id=uuid4(), generation=3,
    )
    verdict = evaluate_replay(
        presented=presented,
        family_generation=5,  # DB has rotated twice past presented
        family_revoked=False,
    )
    assert verdict == RefreshVerdict.REVOKE


def test_evaluate_replay_rejects_higher_than_db():
    """A presented generation > DB means a forged token (we never
    issued that generation). Don't burn the family for a forgery --
    just reject."""
    presented = RefreshClaims(
        user_id=uuid4(), family_id=uuid4(), generation=99,
    )
    verdict = evaluate_replay(
        presented=presented,
        family_generation=5,
        family_revoked=False,
    )
    assert verdict == RefreshVerdict.REJECT


# ── 5 & 6. Already-revoked / unknown family ─────────────────────────


def test_evaluate_replay_rejects_revoked_family():
    presented = RefreshClaims(
        user_id=uuid4(), family_id=uuid4(), generation=5,
    )
    verdict = evaluate_replay(
        presented=presented,
        family_generation=5,
        family_revoked=True,  # revoked by a previous theft event
    )
    assert verdict == RefreshVerdict.REJECT


def test_evaluate_replay_rejects_unknown_family():
    presented = RefreshClaims(
        user_id=uuid4(), family_id=uuid4(), generation=5,
    )
    verdict = evaluate_replay(
        presented=presented,
        family_generation=None,  # no row in refresh_token_families
        family_revoked=False,
    )
    assert verdict == RefreshVerdict.REJECT


# ── Sanity ──────────────────────────────────────────────────────────


def test_refresh_type_constant():
    """Lock down the type-claim string -- changing it would silently
    invalidate every issued refresh in flight."""
    assert REFRESH_TYPE == "refresh"
