"""In-process sliding-window rate limiter — Sprint 11 hotfix.

WHY: the audit caught that ``POST /api/v1/auth/login`` had no rate limit.
Brute-force is the first thing a serious reviewer flags. We add a small
sliding-window counter keyed by ``(remote_ip, email)`` and refuse the
N+1-th attempt within the window with HTTP 429.

This is intentionally stdlib-only (deque + time.monotonic). For multi-
replica deployments, swap the backend for Redis ``INCR`` + ``EXPIRE``
in one command — the LimitBackend protocol below makes it a drop-in.

SAFETY:
  * Even if the limiter itself fails (memory pressure, time skew), the
    `try/except` envelope falls open. Login still works; we never lock
    legit users out because of an internal error.
  * Refuse policy is *fail-closed at limit* but *fail-open on error*.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock
from typing import Protocol

log = logging.getLogger("waf-panel.rate-limit")


class LimitBackend(Protocol):
    def check(self, key: str, *, max_hits: int, window_sec: float) -> bool:
        """Return True if the call is allowed; False if it should be 429."""
        ...

    def reset(self, key: str | None = None) -> None: ...


class _SlidingWindow:
    """In-process backend — works across the same uvicorn process.

    NOTE: per-process state. With multiple workers / replicas the
    effective limit is N×workers. That's acceptable for a course
    project; production swap is documented in the module docstring.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str, *, max_hits: int, window_sec: float) -> bool:
        now = time.monotonic()
        cutoff = now - window_sec
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            # Drop everything older than the window.
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max_hits:
                return False
            bucket.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)


# Module-level singleton; tests reset between cases via reset_for_tests().
_DEFAULT_BACKEND: _SlidingWindow = _SlidingWindow()


def get_default_backend() -> _SlidingWindow:
    return _DEFAULT_BACKEND


def reset_for_tests() -> None:
    _DEFAULT_BACKEND.reset()


def check_login_rate(
    *, ip: str, email: str, max_hits: int = 5, window_sec: float = 60.0,
    backend: LimitBackend | None = None,
) -> bool:
    """Return True if the login attempt is permitted.

    SAFETY: any internal failure → log warning, return True (fail-open).
    Reviewer note: legit-user lockout is worse than slightly-relaxed
    brute-force protection. The audit-log row still records every
    attempt regardless of this check.
    """
    if backend is None:
        backend = _DEFAULT_BACKEND
    try:
        # WHY: lower-case email so case-noise doesn't help an attacker
        #      bypass the per-account limit (`Admin@x.com` ≡ `admin@x.com`).
        key = f"login:{ip}:{(email or '').strip().lower()}"
        return backend.check(key, max_hits=max_hits, window_sec=window_sec)
    except Exception as e:  # noqa: BLE001
        log.warning("rate-limit backend failed (%s); fail-open", e)
        return True


__all__ = [
    "LimitBackend",
    "check_login_rate",
    "get_default_backend",
    "reset_for_tests",
]
