"""Production-startup guard — refuse default admin password in prod.

WHY: pairs with the JWT_SECRET guard. The audit flagged "default admin
/ default JWT secret" as the most likely silent prod-deploy footgun.
The seeded admin row has password 'admin' (matches the login hint),
which is fine for dev / course-defence but lethal if anyone forgets to
rotate before exposing the panel.

This test file exercises the *pure* guard (``_check_admin_password``)
directly — no DB needed. The async wrapper that does the DB lookup is
covered implicitly by the create_app/lifespan path; making it
unit-testable separately is what the pure helper exists for.
"""

from __future__ import annotations

import pytest

from waf_panel.main import _check_admin_password
from waf_panel.security import hash_password

# The literal hash committed in alembic 0003 / tests/conftest.py — this
# is what a fresh deployment will have until rotated. Mirrored here so
# the test fails loudly if anyone changes the seed without updating.
DEFAULT_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$kfIew9gbYywFQIjxXgtBiA$"
    "WiPS5bz9F8qvwWc2Woi51gNJvGCLUltunbZCcWUbl7o"
)


# ── 1. Skip rules — the guard is conservative on purpose ─────────────


def test_skip_in_development_even_with_default_password():
    """SAFETY: dev / course-project default must keep working as-is."""
    _check_admin_password(
        waf_env="development",
        in_memory=False,
        password_hash=DEFAULT_HASH,
        is_active=True,
    )  # must not raise


def test_skip_in_testing_env():
    _check_admin_password(
        waf_env="testing",
        in_memory=False,
        password_hash=DEFAULT_HASH,
        is_active=True,
    )


def test_skip_when_in_memory_repos_active():
    """Test runners use in-memory repos seeded with the default hash —
    the guard must not fire there even if WAF_ENV happens to be set."""
    _check_admin_password(
        waf_env="production",
        in_memory=True,
        password_hash=DEFAULT_HASH,
        is_active=True,
    )


def test_skip_when_admin_row_missing():
    """A brand-new deployment that hasn't run alembic upgrade yet has
    no admin row. The lifespan must still let the app boot so the
    operator can run the migration."""
    _check_admin_password(
        waf_env="production",
        in_memory=False,
        password_hash=None,
        is_active=False,
    )


def test_skip_when_admin_disabled():
    """A disabled admin can't authenticate via /auth/login regardless
    of the password hash — no risk to guard against."""
    _check_admin_password(
        waf_env="production",
        in_memory=False,
        password_hash=DEFAULT_HASH,
        is_active=False,
    )


# ── 2. The actual block: production + active default admin ──────────


def test_blocks_in_production_with_seeded_default_hash():
    with pytest.raises(RuntimeError, match="default password"):
        _check_admin_password(
            waf_env="production",
            in_memory=False,
            password_hash=DEFAULT_HASH,
            is_active=True,
        )


def test_blocks_in_production_with_freshly_rehashed_admin():
    """An operator who naively ran ``hash_password('admin')`` thinking
    they rotated will get a fresh-salt argon2id of the *same* string.
    Verify-based check catches this; literal-equality wouldn't."""
    fresh = hash_password("admin")
    assert fresh != DEFAULT_HASH  # different salt → different literal
    with pytest.raises(RuntimeError, match="default password"):
        _check_admin_password(
            waf_env="production",
            in_memory=False,
            password_hash=fresh,
            is_active=True,
        )


def test_passes_in_production_with_rotated_password():
    """Real rotation: a different password → guard must let the app
    boot."""
    rotated = hash_password("a-real-rotated-password-xY7q")
    _check_admin_password(
        waf_env="production",
        in_memory=False,
        password_hash=rotated,
        is_active=True,
    )  # must not raise


def test_case_insensitive_on_waf_env():
    """``WAF_ENV=Production`` and ``production`` both hit the prod path."""
    with pytest.raises(RuntimeError):
        _check_admin_password(
            waf_env="PRODUCTION",
            in_memory=False,
            password_hash=DEFAULT_HASH,
            is_active=True,
        )


# ── 3. Error message is actionable ───────────────────────────────────


def test_error_message_mentions_runbook_and_email():
    """A failed boot dumps a long traceback into the ops console; the
    one line that matters needs to be self-contained — both the
    affected account and where to find rotation instructions."""
    with pytest.raises(RuntimeError) as exc_info:
        _check_admin_password(
            waf_env="production",
            in_memory=False,
            password_hash=DEFAULT_HASH,
            is_active=True,
        )
    msg = str(exc_info.value)
    assert "admin@example.com" in msg
    assert "runbook" in msg.lower()
