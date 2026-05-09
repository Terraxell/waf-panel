"""Best-effort score cache backed by Redis.

WHY: the same path/query repeats during dashboard polling and during
a scripted attack. Caching saves ~3 ms per hit and shrinks load on
the model. **Cache is best-effort** — Redis being unreachable must
NOT fail the score path.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

log = logging.getLogger("waf-ml-service.cache")


def cache_key(method: str, path: str, query: str) -> str:
    """sha1 over the request fingerprint. WHY: keys must be short and stable."""
    h = hashlib.sha1(usedforsecurity=False)
    h.update(method.upper().encode())
    h.update(b"\x00")
    h.update(path.encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(query.encode("utf-8", "replace"))
    return f"ml:score:{h.hexdigest()[:24]}"


class ScoreCache:
    """Wraps a redis client; treats every operational failure as a miss."""

    def __init__(self, client: Any | None, ttl_sec: int = 30) -> None:
        self._client = client
        self._ttl = ttl_sec

    @property
    def healthy(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(self._client.ping())
        except Exception:  # noqa: BLE001
            return False

    def get(self, key: str) -> dict | None:
        if self._client is None:
            return None
        try:
            blob = self._client.get(key)
        except Exception as e:  # noqa: BLE001
            log.warning("redis GET failed (%s); treating as miss", e)
            return None
        if not blob:
            return None
        try:
            return json.loads(blob)
        except Exception:  # noqa: BLE001
            return None

    def set(self, key: str, value: dict) -> None:
        if self._client is None:
            return
        try:
            self._client.setex(key, self._ttl, json.dumps(value))
        except Exception as e:  # noqa: BLE001
            log.warning("redis SETEX failed (%s); cache populate skipped", e)


def make_cache(redis_url: str, ttl_sec: int) -> ScoreCache:
    """Return a ScoreCache bound to a redis client (or no-op if unreachable)."""
    try:
        import redis  # type: ignore[import-not-found]

        client = redis.Redis.from_url(redis_url, decode_responses=True)
        # Smoke-ping; missing redis is fine, we just disable the cache.
        client.ping()
    except Exception as e:  # noqa: BLE001
        log.info("Redis unavailable at %s (%s); cache disabled", redis_url, e)
        return ScoreCache(client=None, ttl_sec=ttl_sec)
    return ScoreCache(client=client, ttl_sec=ttl_sec)
