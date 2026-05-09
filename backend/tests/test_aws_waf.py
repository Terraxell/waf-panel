"""AWS WAF adapter — verified without boto3 / AWS / network.

WHY: the boto3 client is built behind `client_factory`, so every test
just injects a recording stub. We assert: enabled-flag gating, RFC1918
filtering, dedup, lock-token plumbing, fail-soft on exception,
rate-limit gate.
"""

from __future__ import annotations

import pytest

from waf_panel.integrations.aws_waf import (
    AwsWafConfig,
    reset_rate_limit_for_tests,
    sync_ip_blocklist,
)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    reset_rate_limit_for_tests()
    yield
    reset_rate_limit_for_tests()


def _config(enabled: bool = True) -> AwsWafConfig:
    return AwsWafConfig(
        enabled=enabled,
        region="us-east-1",
        ipset_id="ips-1",
        ipset_name="waf-blocklist",
        scope="REGIONAL",
        rate_limit_seconds=300,
    )


class _RecordingClient:
    """A stub that records every call AWS would have received."""

    def __init__(self, lock_token: str = "tok-1") -> None:
        self.calls: list[tuple[str, dict]] = []
        self._lock_token = lock_token

    def get_ip_set(self, **kwargs):
        self.calls.append(("get_ip_set", kwargs))
        return {"LockToken": self._lock_token, "IPSet": {"Addresses": []}}

    def update_ip_set(self, **kwargs):
        self.calls.append(("update_ip_set", kwargs))
        return {"NextLockToken": "tok-2"}


def test_disabled_flag_short_circuits():
    """No AWS call, no error, all IPs counted as skipped."""
    cfg = _config(enabled=False)
    factory_called = []

    def factory(_cfg):
        factory_called.append(True)
        return _RecordingClient()

    res = sync_ip_blocklist(["1.2.3.4"], cfg, client_factory=factory)
    assert res.pushed == 0
    assert res.skipped == 1
    assert res.error is None
    assert res.rate_limited is False
    assert factory_called == []


def test_pushes_normalised_unique_cidrs():
    cfg = _config()
    client = _RecordingClient()

    # WHY: 8.8.8.8 / 1.1.1.1 are real public addresses; ``ipaddress`` flags
    #      TEST-NET-* and 2001:db8::/32 as private (correct for prod), so
    #      we use globally-routable strings here for a faithful round-trip.
    res = sync_ip_blocklist(
        ["8.8.8.8", "8.8.8.8", " 1.1.1.1 "],
        cfg, client_factory=lambda _c: client,
    )
    assert res.pushed == 2
    assert res.error is None
    update_call = next(c for k, c in client.calls if k == "update_ip_set")
    addrs = update_call["Addresses"]
    assert "8.8.8.8/32" in addrs
    assert "1.1.1.1/32" in addrs
    assert len(addrs) == 2  # dedupe worked


def test_rfc1918_and_loopback_are_filtered_out():
    """Private and loopback addresses must never reach AWS — operator-safe default."""
    cfg = _config()
    client = _RecordingClient()

    res = sync_ip_blocklist(
        ["127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1", "169.254.169.254", "8.8.8.8"],
        cfg, client_factory=lambda _c: client,
    )
    assert res.pushed == 1
    update_call = next(c for k, c in client.calls if k == "update_ip_set")
    assert update_call["Addresses"] == ["8.8.8.8/32"]


def test_invalid_ip_strings_are_skipped_not_raised():
    cfg = _config()
    client = _RecordingClient()

    res = sync_ip_blocklist(
        ["not-an-ip", "999.999.999.999", "2606:4700:4700::1111", "8.8.8.8"],
        cfg, client_factory=lambda _c: client,
    )
    # WHY: 2606:4700:4700::1111 is Cloudflare's public v6 resolver — globally
    #      routable. Junk strings drop, the two real addresses survive.
    assert res.pushed == 2
    assert res.skipped == 2  # the two junk values


def test_lock_token_is_passed_back_to_update_call():
    """SAFETY: AWS WAFv2 requires the LockToken on UpdateIPSet."""
    cfg = _config()
    client = _RecordingClient(lock_token="my-token")
    sync_ip_blocklist(["8.8.8.8"], cfg, client_factory=lambda _c: client)
    update_call = next(c for k, c in client.calls if k == "update_ip_set")
    assert update_call["LockToken"] == "my-token"


def test_aws_exception_returns_error_not_raises():
    """The whole point of fail-soft: panel's own block stack must keep working."""
    cfg = _config()

    class _BrokenClient:
        def get_ip_set(self, **_):
            raise RuntimeError("AWS is having a bad day")

        def update_ip_set(self, **_):
            raise AssertionError("must not be called")

    res = sync_ip_blocklist(["8.8.8.8"], cfg, client_factory=lambda _c: _BrokenClient())
    assert res.error == "AWS is having a bad day"
    assert res.pushed == 0


def test_empty_post_normalisation_skips_aws_call():
    """All-junk input → no boto3 call, no rate-limit clock advance."""
    cfg = _config()
    factory_called = []

    def factory(_cfg):
        factory_called.append(True)
        return _RecordingClient()

    res = sync_ip_blocklist(["bogus", "10.0.0.1"], cfg, client_factory=factory)
    assert res.pushed == 0
    assert res.skipped == 2
    assert factory_called == []  # never even built a client


def test_rate_limit_gate_blocks_second_call_within_window():
    """Two calls within `rate_limit_seconds` → second is a no-op."""
    cfg = _config()
    client = _RecordingClient()

    fake_time = [1000.0]

    def now():
        return fake_time[0]

    r1 = sync_ip_blocklist(["8.8.8.8"], cfg, client_factory=lambda _c: client, now_fn=now)
    assert r1.pushed == 1
    assert r1.rate_limited is False

    fake_time[0] += 60.0  # 1 min later, well inside the 5-min window
    r2 = sync_ip_blocklist(["8.8.4.4"], cfg, client_factory=lambda _c: client, now_fn=now)
    assert r2.rate_limited is True
    assert r2.pushed == 0


def test_rate_limit_gate_releases_after_window():
    cfg = _config()
    client = _RecordingClient()

    fake_time = [1000.0]

    def now():
        return fake_time[0]

    sync_ip_blocklist(["8.8.8.8"], cfg, client_factory=lambda _c: client, now_fn=now)
    fake_time[0] += cfg.rate_limit_seconds + 1
    r = sync_ip_blocklist(["8.8.4.4"], cfg, client_factory=lambda _c: client, now_fn=now)
    assert r.rate_limited is False
    assert r.pushed == 1


def test_ipv6_address_takes_128_prefix():
    cfg = _config()
    client = _RecordingClient()


    res = sync_ip_blocklist(["2606:4700:4700::1111"], cfg, client_factory=lambda _c: client)
    assert res.pushed == 1
    update_call = next(c for k, c in client.calls if k == "update_ip_set")
    assert update_call["Addresses"] == ["2606:4700:4700::1111/128"]
