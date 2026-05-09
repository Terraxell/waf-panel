"""Tests for /api/v1/metrics — overview + timeseries.

Sprint 6: top_attacks reads `top_attacks_lifetime` MV, timeseries reads
`rps_per_minute` MV. Counters still hit `traffic_log` (uniqExact).
"""

from fastapi.testclient import TestClient

from waf_panel.clickhouse_client import InMemoryClickHouseClient


def _seed_overview(ch: InMemoryClickHouseClient) -> None:
    ch.set_fixture("uniqExact(remote_ip)", [
        {"total": 1000, "blocked": 250, "uniq_ips": 17},
    ])
    ch.set_fixture("FROM top_attacks_lifetime", [
        {"path": "/?id=1 OR 1=1", "hits": 80},
        {"path": "/?q=<script>", "hits": 40},
    ])


def test_overview_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/metrics/overview").status_code == 401


def test_overview_returns_aggregates(
    client: TestClient, admin_token: str, in_memory_repos: InMemoryClickHouseClient
) -> None:
    _seed_overview(in_memory_repos)
    res = client.get(
        "/api/v1/metrics/overview",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["requests_24h"] == 1000
    assert body["blocked_24h"] == 250
    assert body["unique_ips_24h"] == 17
    assert abs(body["blocked_share"] - 0.25) < 1e-6
    assert len(body["top_attacks"]) == 2
    assert body["top_attacks"][0]["hits"] == 80


def test_overview_zero_traffic(
    client: TestClient, admin_token: str, in_memory_repos: InMemoryClickHouseClient
) -> None:
    res = client.get(
        "/api/v1/metrics/overview",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "requests_24h": 0,
        "blocked_24h": 0,
        "blocked_share": 0.0,
        "unique_ips_24h": 0,
        "top_attacks": [],
    }


def test_timeseries_minute_uses_mv(
    client: TestClient, admin_token: str, in_memory_repos: InMemoryClickHouseClient
) -> None:
    in_memory_repos.set_fixture("FROM rps_per_minute", [
        {"b": "2026-05-08 13:00:00", "rps": 1.5, "blocked": 2},
        {"b": "2026-05-08 13:01:00", "rps": 2.0, "blocked": 0},
    ])
    res = client.get(
        "/api/v1/metrics/timeseries?bucket=minute&since_hours=1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 2
    assert rows[0]["rps"] == 1.5
    # WHY: confirm we hit the MV table, not the raw scan.
    assert any("rps_per_minute" in q for q in in_memory_repos.calls)


def test_timeseries_hour_aggregates_from_mv(
    client: TestClient, admin_token: str, in_memory_repos: InMemoryClickHouseClient
) -> None:
    in_memory_repos.set_fixture("toStartOfHour(minute)", [
        {"b": "2026-05-08 13:00:00", "rps": 0.5, "blocked": 30},
    ])
    res = client.get(
        "/api/v1/metrics/timeseries?bucket=hour&since_hours=24",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["blocked"] == 30
