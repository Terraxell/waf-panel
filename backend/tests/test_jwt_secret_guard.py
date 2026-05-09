"""Production-startup guard — refuse default JWT_SECRET in prod.

WHY: Sprint 11 hotfix. The audit caught "default admin / default
JWT secret" as the most likely silent prod-deploy footgun. We add an
explicit startup check that fails fast with a readable message.
"""

from __future__ import annotations

import pytest


def _make_settings(**overrides):
    """Build a Settings object with explicit overrides — bypass the
    cached singleton from `get_settings()` so tests don't pollute each other.
    """
    from waf_panel.config import Settings

    base = dict(
        jwt_secret="this-is-a-real-32-char-prod-secret-aaa",
        waf_env="development",
    )
    base.update(overrides)
    return Settings(**base)


def test_guard_no_op_in_development_with_default_secret():
    """SAFETY: dev / test must keep working without ceremony."""
    from waf_panel.main import _validate_settings

    s = _make_settings(jwt_secret="dev-secret-do-not-use", waf_env="development")
    _validate_settings(s)  # must not raise


def test_guard_no_op_in_test_env():
    from waf_panel.main import _validate_settings

    s = _make_settings(jwt_secret="test-secret-test-secret-test", waf_env="testing")
    _validate_settings(s)


def test_guard_blocks_default_secret_in_production():
    from waf_panel.main import _validate_settings

    s = _make_settings(
        jwt_secret="change_me_in_a_real_deployment",
        waf_env="production",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET is a known default"):
        _validate_settings(s)


def test_guard_blocks_short_secret_in_production():
    from waf_panel.main import _validate_settings

    s = _make_settings(jwt_secret="too-short-secret-15c", waf_env="production")
    with pytest.raises(RuntimeError, match="JWT_SECRET is < 32 chars"):
        _validate_settings(s)


def test_guard_passes_long_random_secret_in_production():
    """Real prod secret: 32+ chars, not in the blocklist → pass."""
    from waf_panel.main import _validate_settings

    s = _make_settings(
        jwt_secret="a" * 32,  # placeholder for `openssl rand -hex 32` output
        waf_env="production",
    )
    _validate_settings(s)


def test_guard_case_insensitive_on_env_value():
    """`WAF_ENV=Production` and `production` both trigger the prod path."""
    from waf_panel.main import _validate_settings

    s = _make_settings(
        jwt_secret="dev-secret-do-not-use",
        waf_env="PRODUCTION",
    )
    with pytest.raises(RuntimeError):
        _validate_settings(s)


def test_create_app_in_production_with_bad_secret_raises(monkeypatch):
    """End-to-end: create_app() refuses to construct the app in prod."""
    monkeypatch.setenv("WAF_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "dev-secret-do-not-use")
    # Reset the lru_cache so the new env vars actually land.
    from waf_panel.config import get_settings
    get_settings.cache_clear()

    from waf_panel.main import create_app
    with pytest.raises(RuntimeError):
        create_app()

    # Restore for downstream tests in the same process.
    monkeypatch.setenv("WAF_ENV", "development")
    get_settings.cache_clear()
