"""Contract tests for the in-memory ClickHouse mock."""

import pytest

from waf_panel.clickhouse_client import InMemoryClickHouseClient


@pytest.mark.asyncio
async def test_returns_fixture_when_query_substring_matches() -> None:
    ch = InMemoryClickHouseClient(fixtures={"FROM traffic_log": [{"x": 1}]})
    rows = await ch.query_json("SELECT count() FROM traffic_log WHERE ...")
    assert rows == [{"x": 1}]


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_fixture_matches() -> None:
    ch = InMemoryClickHouseClient()
    assert await ch.query_json("SELECT 1") == []


@pytest.mark.asyncio
async def test_records_call_history() -> None:
    ch = InMemoryClickHouseClient()
    await ch.query_json("SELECT 1")
    await ch.query_json("SELECT 2")
    assert len(ch.calls) == 2
    assert ch.calls[0].startswith("SELECT 1")


@pytest.mark.asyncio
async def test_set_fixture_at_runtime() -> None:
    ch = InMemoryClickHouseClient()
    ch.set_fixture("modsec", [{"hits": 42}])
    rows = await ch.query_json("WHERE event_type = 'modsec'")
    assert rows == [{"hits": 42}]
