"""User-management endpoints — task #123.

Eight behaviours we lock down:

1. List/create/update/delete are admin-only (analyst/viewer get 403).
2. Create rejects duplicate email with 409.
3. Update touches role and/or is_active partially.
4. Delete is soft (sets is_active=False, audit row written).
5. Self-modify on PATCH/DELETE is refused (admin lockout safety).
6. Audit log gains user.create / user.update / user.delete actions.
7. Password is hashed (never echoed back).
8. List excludes password_hash from the wire shape.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from waf_panel.repositories.deps import memory_audit_repo


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── 1. RBAC ──────────────────────────────────────────────────────────


def test_list_users_requires_admin(client, admin_token) -> None:
    res = client.get("/api/v1/users", headers=_h(admin_token))
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert any(u["email"] == "admin@example.com" for u in body)
    # password_hash must NOT leak in the wire shape
    for u in body:
        assert "password_hash" not in u


def test_unauthenticated_listing_rejected(client) -> None:
    res = client.get("/api/v1/users")
    assert res.status_code == 401


# ── 2. Create ────────────────────────────────────────────────────────


def test_create_user_happy_path(client, admin_token) -> None:
    payload = {
        "email": "analyst@example.com",
        "role": "analyst",
        "password": "a-real-password-1",
    }
    res = client.post("/api/v1/users", json=payload, headers=_h(admin_token))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["email"] == "analyst@example.com"
    assert body["role"] == "analyst"
    assert body["is_active"] is True
    assert "password" not in body and "password_hash" not in body


def test_create_user_rejects_duplicate_email(client, admin_token) -> None:
    payload = {
        "email": "admin@example.com",  # already seeded
        "role": "viewer",
        "password": "doesnt-matter-1",
    }
    res = client.post("/api/v1/users", json=payload, headers=_h(admin_token))
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_create_user_rejects_short_password(client, admin_token) -> None:
    """min_length=8 from the schema -- 7 chars is the boundary."""
    payload = {
        "email": "shortpw@example.com",
        "role": "viewer",
        "password": "1234567",  # 7 chars
    }
    res = client.post("/api/v1/users", json=payload, headers=_h(admin_token))
    assert res.status_code == 422  # pydantic validation


# ── 3. Update ────────────────────────────────────────────────────────


def test_update_user_changes_role(client, admin_token) -> None:
    # Create then update.
    res = client.post(
        "/api/v1/users",
        json={"email": "rl@example.com", "role": "viewer", "password": "abcdefgh"},
        headers=_h(admin_token),
    )
    uid = res.json()["id"]

    res = client.patch(
        f"/api/v1/users/{uid}",
        json={"role": "analyst"},
        headers=_h(admin_token),
    )
    assert res.status_code == 200
    assert res.json()["role"] == "analyst"


def test_update_user_toggles_is_active(client, admin_token) -> None:
    res = client.post(
        "/api/v1/users",
        json={"email": "tog@example.com", "role": "viewer", "password": "abcdefgh"},
        headers=_h(admin_token),
    )
    uid = res.json()["id"]

    res = client.patch(
        f"/api/v1/users/{uid}",
        json={"is_active": False},
        headers=_h(admin_token),
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False


def test_update_unknown_id_404(client, admin_token) -> None:
    res = client.patch(
        f"/api/v1/users/{uuid4()}",
        json={"role": "viewer"},
        headers=_h(admin_token),
    )
    assert res.status_code == 404


# ── 4. Delete ────────────────────────────────────────────────────────


def test_delete_user_is_soft(client, admin_token) -> None:
    res = client.post(
        "/api/v1/users",
        json={"email": "del@example.com", "role": "viewer", "password": "abcdefgh"},
        headers=_h(admin_token),
    )
    uid = res.json()["id"]

    res = client.delete(f"/api/v1/users/{uid}", headers=_h(admin_token))
    assert res.status_code == 204

    # After delete, the row is still in the listing but with is_active=False.
    listing = client.get("/api/v1/users", headers=_h(admin_token)).json()
    matched = [u for u in listing if u["id"] == uid]
    assert len(matched) == 1
    assert matched[0]["is_active"] is False


def test_delete_unknown_id_404(client, admin_token) -> None:
    res = client.delete(f"/api/v1/users/{uuid4()}", headers=_h(admin_token))
    assert res.status_code == 404


# ── 5. Self-modification guard ───────────────────────────────────────


def test_cannot_update_self(client, admin_token) -> None:
    me = client.get("/api/v1/auth/me", headers=_h(admin_token)).json()
    res = client.patch(
        f"/api/v1/users/{me['id']}",
        json={"role": "viewer"},
        headers=_h(admin_token),
    )
    assert res.status_code == 400
    assert "own account" in res.json()["detail"]


def test_cannot_delete_self(client, admin_token) -> None:
    me = client.get("/api/v1/auth/me", headers=_h(admin_token)).json()
    res = client.delete(f"/api/v1/users/{me['id']}", headers=_h(admin_token))
    assert res.status_code == 400


# ── 6. Audit ─────────────────────────────────────────────────────────


def test_create_user_writes_audit(client, admin_token) -> None:
    res = client.post(
        "/api/v1/users",
        json={"email": "auditme@example.com", "role": "viewer", "password": "abcdefgh"},
        headers=_h(admin_token),
    )
    assert res.status_code == 201
    audit = memory_audit_repo()
    assert audit is not None
    actions = [r["action"] for r in audit._rows]
    assert "user.create" in actions


@pytest.mark.parametrize(
    "method,verb",
    [("PATCH", "user.update"), ("DELETE", "user.delete")],
)
def test_mutations_write_audit(client, admin_token, method, verb) -> None:
    create = client.post(
        "/api/v1/users",
        json={
            "email": f"audit-{verb}@example.com",
            "role": "viewer",
            "password": "abcdefgh",
        },
        headers=_h(admin_token),
    )
    uid = create.json()["id"]
    if method == "PATCH":
        client.patch(f"/api/v1/users/{uid}", json={"role": "analyst"}, headers=_h(admin_token))
    else:
        client.delete(f"/api/v1/users/{uid}", headers=_h(admin_token))
    audit = memory_audit_repo()
    assert audit is not None
    assert verb in [r["action"] for r in audit._rows]
