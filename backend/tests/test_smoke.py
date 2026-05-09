"""Smoke tests — verify the gateway boots and the contract holds.

The full test suite (DB-backed repositories, RBAC matrix, audit log) lands in
Sprint 4. These tests are the floor: every commit must keep them green.
"""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_login_with_seed_admin(client: TestClient) -> None:
    res = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "admin"})
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_login_rejects_unknown_user(client: TestClient) -> None:
    res = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "x"})
    assert res.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_user_for_valid_token(client: TestClient, admin_token: str) -> None:
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_rules_crud_happy_path(client: TestClient, admin_token: str) -> None:
    h = {"Authorization": f"Bearer {admin_token}"}

    # initially empty
    assert client.get("/api/v1/rules", headers=h).json() == []

    # create
    payload = {
        "rule_key": "test-001",
        "source": "custom",
        "severity": 3,
        "action": "log",
        "description": "fixture rule for the smoke suite",
        "body": "SecRule REQUEST_URI \"@contains test\" \"id:9999,deny\"",
        "enabled": True,
    }
    res = client.post("/api/v1/rules", headers=h, json=payload)
    assert res.status_code == 201, res.text
    rule_id = res.json()["id"]

    # duplicate key conflict
    assert client.post("/api/v1/rules", headers=h, json=payload).status_code == 409

    # update
    res = client.put(f"/api/v1/rules/{rule_id}", headers=h, json={"action": "block"})
    assert res.status_code == 200
    assert res.json()["action"] == "block"

    # delete
    assert client.delete(f"/api/v1/rules/{rule_id}", headers=h).status_code == 204
    assert client.get(f"/api/v1/rules/{rule_id}", headers=h).status_code == 404


def test_openapi_lists_all_endpoints(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    paths = set(spec["paths"].keys())
    assert {"/health", "/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/rules"} <= paths
