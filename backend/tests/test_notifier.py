"""Notification webhook adapter — Sprint 13."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _reset_notifier():
    from waf_panel.integrations.notifier import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


def _run(coro):
    return asyncio.run(coro)


def _stub_httpx(monkeypatch, *, status_code: int = 200, raise_exc: Exception | None = None):
    """Install a fake httpx module for the notifier's late-bound import."""
    calls: list[dict] = []

    class _Resp:
        def __init__(self, status):
            self.status_code = status

    class _Client:
        def __init__(self, *a, **kw):
            calls.append({"init": kw})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            calls.append({"url": url, "json": json})
            if raise_exc is not None:
                raise raise_exc
            return _Resp(status_code)

    fake = types.ModuleType("httpx")
    fake.AsyncClient = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake)
    return calls


def test_notify_disabled_when_no_url():
    from waf_panel.integrations.notifier import NotifierConfig, notify

    cfg = NotifierConfig(enabled=False, webhook_url="")
    res = _run(notify(channel="drift", text="hello", config=cfg))
    assert res.sent is False
    assert res.skipped_reason == "disabled"


def test_notify_sends_slack_payload(monkeypatch):
    from waf_panel.integrations.notifier import NotifierConfig, notify

    calls = _stub_httpx(monkeypatch)
    cfg = NotifierConfig(enabled=True, webhook_url="https://hooks.example.com/abc")
    res = _run(notify(channel="drift", text="hello", config=cfg))
    assert res.sent is True
    posted = next(c for c in calls if "url" in c)
    assert posted["url"] == "https://hooks.example.com/abc"
    assert posted["json"] == {"text": "hello"}


def test_rate_limit_within_cooldown(monkeypatch):
    from waf_panel.integrations.notifier import NotifierConfig, notify

    _stub_httpx(monkeypatch)
    cfg = NotifierConfig(
        enabled=True,
        webhook_url="https://hooks.example.com/abc",
        cooldown_sec=60,
    )

    fake_time = [1000.0]
    now = lambda: fake_time[0]  # noqa: E731

    r1 = _run(notify(channel="drift", text="first", config=cfg, now_fn=now))
    assert r1.sent is True

    fake_time[0] += 30  # within the 60s window
    r2 = _run(notify(channel="drift", text="second", config=cfg, now_fn=now))
    assert r2.sent is False
    assert r2.skipped_reason == "rate_limited"


def test_rate_limit_releases_after_cooldown(monkeypatch):
    from waf_panel.integrations.notifier import NotifierConfig, notify

    _stub_httpx(monkeypatch)
    cfg = NotifierConfig(
        enabled=True,
        webhook_url="https://hooks.example.com/abc",
        cooldown_sec=60,
    )

    fake_time = [1000.0]
    now = lambda: fake_time[0]  # noqa: E731

    _run(notify(channel="drift", text="first", config=cfg, now_fn=now))
    fake_time[0] += 61
    r2 = _run(notify(channel="drift", text="second", config=cfg, now_fn=now))
    assert r2.sent is True


def test_different_channels_are_independent(monkeypatch):
    """Drift alerts and threshold-update notifications shouldn't gate each other."""
    from waf_panel.integrations.notifier import NotifierConfig, notify

    _stub_httpx(monkeypatch)
    cfg = NotifierConfig(
        enabled=True,
        webhook_url="https://hooks.example.com/abc",
        cooldown_sec=60,
    )

    fake_time = [1000.0]
    now = lambda: fake_time[0]  # noqa: E731

    r1 = _run(notify(channel="drift", text="A", config=cfg, now_fn=now))
    r2 = _run(notify(channel="threshold", text="B", config=cfg, now_fn=now))
    assert r1.sent is True
    assert r2.sent is True


def test_fail_soft_on_exception(monkeypatch):
    """SAFETY: webhook explosion must not propagate."""
    from waf_panel.integrations.notifier import NotifierConfig, notify

    _stub_httpx(monkeypatch, raise_exc=ConnectionError("dns fail"))
    cfg = NotifierConfig(enabled=True, webhook_url="https://hooks.example.com/abc")
    res = _run(notify(channel="drift", text="x", config=cfg))
    assert res.sent is False
    assert res.error == "dns fail"


def test_fail_soft_on_http_4xx(monkeypatch):
    from waf_panel.integrations.notifier import NotifierConfig, notify

    _stub_httpx(monkeypatch, status_code=403)
    cfg = NotifierConfig(enabled=True, webhook_url="https://hooks.example.com/abc")
    res = _run(notify(channel="drift", text="x", config=cfg))
    assert res.sent is False
    assert res.error == "http_403"


def test_config_from_env(monkeypatch):
    from waf_panel.integrations.notifier import config_from_env

    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://example.com/hook")
    monkeypatch.setenv("NOTIFY_COOLDOWN_SEC", "30")
    cfg = config_from_env()
    assert cfg.enabled is True
    assert cfg.webhook_url == "https://example.com/hook"
    assert cfg.cooldown_sec == 30


def test_config_from_env_disabled_by_default(monkeypatch):
    from waf_panel.integrations.notifier import config_from_env

    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    cfg = config_from_env()
    assert cfg.enabled is False
