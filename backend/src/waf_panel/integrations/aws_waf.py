"""AWS WAF IPSet sync — opt-in, fail-soft, one-direction.

WHY: ADR-0012. The panel is the source of truth; AWS is a downstream
replica. We never read AWS counters back. boto3 is imported lazily so
unit tests don't pull the dependency unless the flag is on.

CIDR formatting note: AWS WAF v2 IPSets accept a list of CIDR strings
(e.g. ``"203.0.113.7/32"``). We pass single addresses as ``/32``
(``/128`` for IPv6) so the IPSet's IPAddressVersion stays consistent.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from dataclasses import dataclass

log = logging.getLogger("waf-panel.integrations.aws_waf")


@dataclass(frozen=True)
class AwsWafConfig:
    enabled: bool
    region: str
    ipset_id: str
    ipset_name: str
    scope: str  # "REGIONAL" | "CLOUDFRONT"
    rate_limit_seconds: int = 300


@dataclass
class SyncResult:
    pushed: int
    skipped: int
    error: str | None
    rate_limited: bool


def _normalise(ip: str) -> str | None:
    """Return a CIDR string the IPSet will accept, or None if junk.

    SAFETY: rejects loopback, link-local, RFC1918 private space — those
    don't belong in a public-edge blocklist, and shipping them to AWS
    would be a self-inflicted incident.
    """
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_multicast:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        return f"{addr.compressed}/128"
    return f"{addr.compressed}/32"


# Module-level mutable state, scoped to the process. Sprint 11 will move
# this into Redis so multiple gateway replicas share the rate-limit floor.
_LAST_SYNC_TS: dict[str, float] = {}


def _client_factory(config: AwsWafConfig):
    """Late-bound import so tests don't require boto3."""
    import boto3  # type: ignore[import-not-found]

    return boto3.client("wafv2", region_name=config.region)


def sync_ip_blocklist(
    ips: list[str],
    config: AwsWafConfig,
    *,
    client_factory=_client_factory,
    now_fn=time.time,
) -> SyncResult:
    """Push a deduplicated, normalised IP blocklist into the configured IPSet.

    Behaviour:
      * Returns ``rate_limited=True`` and skips the call if we synced within
        ``config.rate_limit_seconds`` of the last successful push.
      * On any AWS error the result carries ``error`` set; the caller
        records it via audit_log. We never raise.
    """
    if not config.enabled:
        return SyncResult(pushed=0, skipped=len(ips), error=None, rate_limited=False)

    last = _LAST_SYNC_TS.get(config.ipset_id, 0.0)
    if now_fn() - last < config.rate_limit_seconds:
        return SyncResult(pushed=0, skipped=len(ips), error=None, rate_limited=True)

    cidrs: list[str] = []
    skipped = 0
    seen: set[str] = set()
    for ip in ips:
        c = _normalise(ip)
        if c is None or c in seen:
            skipped += 1
            continue
        seen.add(c)
        cidrs.append(c)

    if not cidrs:
        # WHY: don't poke AWS just to write an empty list — keeps the
        #      audit log readable and the AWS API quota intact.
        return SyncResult(pushed=0, skipped=skipped, error=None, rate_limited=False)

    try:
        client = client_factory(config)
        # AWS WAFv2 requires the IPSet's current `LockToken` for the update.
        head = client.get_ip_set(
            Name=config.ipset_name, Scope=config.scope, Id=config.ipset_id,
        )
        lock_token = head["LockToken"]
        client.update_ip_set(
            Name=config.ipset_name,
            Scope=config.scope,
            Id=config.ipset_id,
            Addresses=cidrs,
            LockToken=lock_token,
        )
    except Exception as e:  # noqa: BLE001 — fail soft, audit upstream
        log.error("AWS WAF sync failed: %s", e)
        return SyncResult(pushed=0, skipped=skipped, error=str(e), rate_limited=False)

    _LAST_SYNC_TS[config.ipset_id] = now_fn()
    return SyncResult(pushed=len(cidrs), skipped=skipped, error=None, rate_limited=False)


def reset_rate_limit_for_tests() -> None:
    """Test helper — clears the in-process rate-limit floor."""
    _LAST_SYNC_TS.clear()


__all__ = [
    "AwsWafConfig",
    "SyncResult",
    "reset_rate_limit_for_tests",
    "sync_ip_blocklist",
]
