"""Login rate-limit — Sprint 11 hotfix.

Behaviour:
  * 5 attempts per (ip, email) per 60 s succeed (or 401 on bad creds).
  * 6th attempt → 429 regardless of credentials.
  * Different email or different IP → independent bucket.
  * Backend-failure path falls open (legit users not locked out).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Snap rate-limit buckets back to zero between tests."""
    from waf_panel.security_rate_limit import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


def test_correct_login_succeeds_within_window(client):
    # 5 successful logins in a row — rate limit must allow them all.
    for _ in range(5):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin"},
        )
        assert r.status_code == 200, r.text


def test_sixth_attempt_returns_429(client):
    """SAFETY: brute-force gating fires regardless of credentials — even
    a valid user's 6th attempt within 60s is throttled. Sprint 12 may
    reset on success; for now the simpler always-throttle is correct."""
    # Wrong password 5 times → all 401, but bucket fills up.
    for i in range(5):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "victim@example.com", "password": f"wrong-{i}"},
        )
        assert r.status_code == 401
    # 6th must be 429.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": "still-wrong"},
    )
    assert r.status_code == 429
    assert "too many" in r.json().get("detail", "").lower()


def test_different_email_uses_independent_bucket(client):
    """Brute-forcing user A must not lock out user B — keys are per-email."""
    for i in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "a@example.com", "password": f"x-{i}"},
        )
    # B's first attempt must still succeed (same IP, different email).
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert r.status_code == 200


def test_email_case_normalised_in_rate_limit_key(client):
    """`Admin@x.com` and `admin@x.com` must share the same bucket so an
    attacker can't bypass the per-account limit by varying case.
    """
    # 5 wrong attempts on a mixed-case spelling.
    for i in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "Admin@example.com", "password": f"x-{i}"},
        )
    # 6th attempt with the lowercase form must hit the same bucket → 429.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    assert r.status_code == 429


def test_rate_limit_check_falls_open_on_backend_error(client, monkeypatch):
    """If the limit backend itself raises, login still works (fail-open).
    Audit row would still record the attempt via the service layer.
    """
    from waf_panel.security_rate_limit import _SlidingWindow

    def _broken_check(self, key, *, max_hits, window_sec):  # noqa: ARG001
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(_SlidingWindow, "check", _broken_check)
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    # Login goes through despite the broken limiter.
    assert r.status_code == 200


def test_pure_unit_check_login_rate():
    """Direct unit check on the helper — independent of FastAPI."""
    from waf_panel.security_rate_limit import _SlidingWindow, check_login_rate

    backend = _SlidingWindow()
    for _ in range(5):
        assert check_login_rate(
            ip="1.2.3.4", email="x@y.z",
            max_hits=5, window_sec=60.0, backend=backend,
        )
    # 6th in the same window — refused.
    assert not check_login_rate(
        ip="1.2.3.4", email="x@y.z",
        max_hits=5, window_sec=60.0, backend=backend,
    )
    # Different IP → independent.
    assert check_login_rate(
        ip="5.6.7.8", email="x@y.z",
        max_hits=5, window_sec=60.0, backend=backend,
    )
