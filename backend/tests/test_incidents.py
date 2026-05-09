"""Tests for /api/v1/incidents."""

from fastapi.testclient import TestClient

from waf_panel.clickhouse_client import InMemoryClickHouseClient


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/incidents").status_code == 401


def test_returns_rows_with_default_filters(
    client: TestClient, admin_token: str, in_memory_repos: InMemoryClickHouseClient
) -> None:
    in_memory_repos.set_fixture("FROM traffic_log", [
        {
            "ts": "2026-05-08 13:50:00",
            "event_type": "modsec",
            "remote_ip": "127.0.0.1",
            "method": "GET",
            "path": "/?id=1 OR 1=1",
            "status": 403,
        },
        {
            "ts": "2026-05-08 13:51:00",
            "event_type": "modsec",
            "remote_ip": "127.0.0.1",
            "method": "GET",
            "path": "/?q=<script>",
            "status": 403,
        },
    ])
    res = client.get(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 2
    assert rows[0]["status"] == 403
    assert rows[0]["event_type"] == "modsec"


def test_only_blocked_filter_changes_query(
    client: TestClient, admin_token: str, in_memory_repos: InMemoryClickHouseClient
) -> None:
    in_memory_repos.set_fixture("FROM traffic_log", [])
    client.get(
        "/api/v1/incidents?only_blocked=false",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # WHY: when only_blocked is False, the SQL must NOT contain the
    #      modsec event-type filter.
    last_sql = in_memory_repos.calls[-1]
    assert "event_type = 'modsec'" not in last_sql


def test_ip_filter_quoted_into_sql(
    client: TestClient, admin_token: str, in_memory_repos: InMemoryClickHouseClient
) -> None:
    in_memory_repos.set_fixture("FROM traffic_log", [])
    client.get(
        "/api/v1/incidents?ip=10.0.0.1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert "remote_ip = '10.0.0.1'" in in_memory_repos.calls[-1]
