"""Notification webhook adapter — Sprint 13 (audit C-list item 18b).

WHY: drift alerts and admin-level config changes deserve a push signal,
not just an audit-log row that nobody reads. We support a single
generic webhook (Slack-compatible payload by default) so an operator
can wire it to whatever Incoming-Webhook URL they have — Slack,
Discord, MS Teams, Mattermost, custom relay, or a fixture HTTP server
in tests.

Design contract:

  * **Opt-in.** Disabled when ``NOTIFY_WEBHOOK_URL`` is empty (default).
    Backend keeps working as before.
  * **Fail-soft.** Any HTTP error is swallowed — we audit-log it but
    never raise out of the trigger code path. Drift workers / threshold
    edits must keep going even if Slack is having a bad day.
  * **Rate-limit floor.** Per-channel cooldown (env-configurable, 60 s
    default) prevents notification storms when drift flaps. The
    in-process bucket is fine for one backend replica; Sprint 14+ moves
    it to Redis when we run multi-replica.
  * **Body shape.** Slack's standard ``{"text": "..."}`` works on most
    receivers without modification. Operators with non-Slack relays
    can preformat their own incoming-webhook adapter.

The notifier is intentionally not in the request critical path. It is
called from drift_worker and from threshold-PUT side-effects.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger("waf-panel.integrations.notifier")


@dataclass(frozen=True)
class NotifierConfig:
    enabled: bool
    webhook_url: str
    cooldown_sec: int = 60
    timeout_sec: float = 3.0


@dataclass
class NotifyResult:
    sent: bool
    skipped_reason: str | None
    error: str | None


# WHY: per-channel last-sent timestamps. `channel` is operator-meaningful
# string — e.g. "drift-alert", "threshold-update". Reused buckets allow
# different signals to flap independently.
_LAST_SENT: dict[str, float] = {}


def reset_for_tests() -> None:
    """Clear per-channel cooldowns. Called by test fixtures."""
    _LAST_SENT.clear()


def _httpx_client():
    """Late-bound httpx — keeps notifier import-light when notifications
    aren't enabled.
    """
    import httpx

    return httpx


async def notify(
    *,
    channel: str,
    text: str,
    config: NotifierConfig,
    now_fn=time.monotonic,
) -> NotifyResult:
    """Send one Slack-compatible webhook payload.

    SAFETY: never raises. The caller (drift worker, audit hook) must
    keep going regardless of webhook health.
    """
    if not config.enabled or not config.webhook_url:
        return NotifyResult(sent=False, skipped_reason="disabled", error=None)

    last = _LAST_SENT.get(channel, 0.0)
    if now_fn() - last < config.cooldown_sec:
        return NotifyResult(sent=False, skipped_reason="rate_limited", error=None)

    httpx = _httpx_client()
    payload = {"text": text}
    try:
        async with httpx.AsyncClient(timeout=config.timeout_sec, trust_env=False) as client:
            resp = await client.post(config.webhook_url, json=payload)
        if resp.status_code >= 400:
            log.warning(
                "notifier got HTTP %d from webhook (channel=%s)", resp.status_code, channel,
            )
            return NotifyResult(
                sent=False, skipped_reason=None,
                error=f"http_{resp.status_code}",
            )
    except Exception as e:  # noqa: BLE001 — fail-soft contract
        log.warning("notifier failed for channel=%s: %s", channel, e)
        return NotifyResult(sent=False, skipped_reason=None, error=str(e))

    _LAST_SENT[channel] = now_fn()
    return NotifyResult(sent=True, skipped_reason=None, error=None)


def config_from_env() -> NotifierConfig:
    """Build a NotifierConfig from the same env vars the gateway reads."""
    import os

    url = os.environ.get("NOTIFY_WEBHOOK_URL", "").strip()
    cooldown = int(os.environ.get("NOTIFY_COOLDOWN_SEC", "60"))
    return NotifierConfig(
        enabled=bool(url),
        webhook_url=url,
        cooldown_sec=cooldown,
    )


__all__ = [
    "NotifierConfig",
    "NotifyResult",
    "config_from_env",
    "notify",
    "reset_for_tests",
]
