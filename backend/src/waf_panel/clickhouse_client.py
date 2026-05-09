"""ClickHouse async client + DI provider.

WHY: same pattern as the Postgres repository — endpoints depend on a
     `Protocol`, the production path uses an httpx-backed real client,
     tests inject the in-memory mock. ClickHouse exposes an HTTP endpoint
     at :8123 that takes SQL in the body and returns JSON via the
     `FORMAT JSONEachRow` clause; we don't need a separate driver.
"""

from __future__ import annotations

from typing import Annotated, Any, Protocol

import httpx
from fastapi import Depends

from .config import get_settings


class ClickHouseClient(Protocol):
    """Minimal protocol the API depends on — easy to mock."""

    async def query_json(self, sql: str) -> list[dict[str, Any]]: ...


class HttpClickHouseClient:
    """Production client — talks HTTP to ClickHouse."""

    def __init__(self, base_url: str, user: str, password: str, database: str) -> None:
        # WHY: persistent client reuses TCP/TLS, important when the dashboard
        #      polls every 30 s. Lifespan (app shutdown) closes it.
        self._client = httpx.AsyncClient(
            base_url=base_url,
            auth=(user, password),
            timeout=httpx.Timeout(5.0, connect=2.0),
        )
        self._database = database

    async def query_json(self, sql: str) -> list[dict[str, Any]]:
        # WHY: ClickHouse `FORMAT JSONEachRow` returns one JSON object per
        #      line. We append it once here so callers stay declarative.
        body = f"{sql}\nFORMAT JSONEachRow"
        resp = await self._client.post(
            "/", params={"database": self._database}, content=body.encode("utf-8")
        )
        resp.raise_for_status()
        text = resp.text.strip()
        if not text:
            return []
        import json

        return [json.loads(line) for line in text.splitlines() if line.strip()]

    async def close(self) -> None:
        await self._client.aclose()


class InMemoryClickHouseClient:
    """Test double — returns canned rows keyed by the SQL string.

    SAFETY: SQL match is a substring check, not a real parse. Tests should
            use distinct enough query fragments.
    """

    def __init__(self, fixtures: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._fixtures = fixtures or {}
        self.calls: list[str] = []

    async def query_json(self, sql: str) -> list[dict[str, Any]]:
        self.calls.append(sql)
        for needle, rows in self._fixtures.items():
            if needle in sql:
                return list(rows)
        return []

    def set_fixture(self, needle: str, rows: list[dict[str, Any]]) -> None:
        self._fixtures[needle] = rows


# ── DI plumbing ──────────────────────────────────────────────────────

_real_client: HttpClickHouseClient | None = None
_in_memory: InMemoryClickHouseClient | None = None


def _get_real() -> HttpClickHouseClient:
    global _real_client
    if _real_client is None:
        s = get_settings()
        _real_client = HttpClickHouseClient(
            base_url=f"http://{s.ch_host}:{s.ch_http_port}",
            user=s.ch_user,
            password=s.ch_password,
            database=s.ch_db,
        )
    return _real_client


def use_in_memory_clickhouse(fixtures: dict[str, list[dict[str, Any]]] | None = None) -> InMemoryClickHouseClient:
    """Test hook: replace the real client with a deterministic stub."""
    global _in_memory
    _in_memory = InMemoryClickHouseClient(fixtures=fixtures)
    return _in_memory


def reset_in_memory_clickhouse() -> None:
    global _in_memory
    _in_memory = None


def get_clickhouse() -> ClickHouseClient:
    if _in_memory is not None:
        return _in_memory
    return _get_real()


async def dispose_clickhouse() -> None:
    global _real_client
    if _real_client is not None:
        await _real_client.close()
    _real_client = None


ClickHouseDep = Annotated[ClickHouseClient, Depends(get_clickhouse)]


__all__ = [
    "ClickHouseClient",
    "ClickHouseDep",
    "HttpClickHouseClient",
    "InMemoryClickHouseClient",
    "dispose_clickhouse",
    "get_clickhouse",
    "reset_in_memory_clickhouse",
    "use_in_memory_clickhouse",
]
