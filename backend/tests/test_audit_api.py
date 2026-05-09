"""Tests for /api/v1/audit — admin-only read-only endpoint."""

from fastapi.testclient import TestClient


def _login_admin(client: TestClient) -> str:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin"},
    )
    return res.json()["access_token"]


def test_audit_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/audit").status_code == 401


def test_audit_returns_login_records(client: TestClient, admin_token: str) -> None:
    # The admin_token fixture already logged in once → there must be at
    # least one `auth.login.ok` audit row.
    res = client.get(
        "/api/v1/audit",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    actions = [r["action"] for r in rows]
    assert "auth.login.ok" in actions


def test_audit_action_prefix_filter(client: TestClient, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    # Trigger a failed login to get an `auth.login.failed` row.
    client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"})
    res = client.get("/api/v1/audit?action_prefix=auth.login.failed", headers=h)
    assert res.status_code == 200
    rows = res.json()
    assert all(r["action"].startswith("auth.login.failed") for r in rows)
    assert len(rows) >= 1


def test_audit_records_rule_lifecycle(client: TestClient, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}
    rule_id = client.post("/api/v1/rules", headers=h, json={
        "rule_key": "audit-test-1",
        "source": "custom",
        "severity": 2,
        "action": "log",
        "description": "fixture",
        "body": "SecRule REQUEST_URI \"@contains test\" \"id:9991,deny\"",
        "enabled": True,
    }).json()["id"]
    client.delete(f"/api/v1/rules/{rule_id}", headers=h)

    res = client.get("/api/v1/audit?action_prefix=rule.", headers=h)
    actions = [r["action"] for r in res.json()]
    assert "rule.create" in actions
    assert "rule.delete" in actions
