"""Bulk-import rules — (audit C-list item 18a)."""

from __future__ import annotations

import pytest


def _rule(key: str, body: str = "SecRule REQUEST_URI \"@contains /x\" \"id:1,phase:1,deny\"") -> dict:
    return {
        "rule_key": key,
        "source": "custom",
        "severity": 3,
        "action": "log",
        "description": f"test {key}",
        "body": body,
        "enabled": True,
    }


def _auth(_client, admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_dry_run_validates_without_creating(client, admin_token):
    r = client.post(
        "/api/v1/rules/bulk",
        json={"rules": [_rule("dr-001"), _rule("dr-002")], "dry_run": True},
        headers=_auth(client, admin_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["total"] == 2
    assert body["created"] == 2
    assert body["conflicts"] == 0
    for it in body["items"]:
        assert it["status"] == "would_create"
        assert it["rule_id"] is None

    # SAFETY: dry-run must NOT have created any rule.
    listed = client.get("/api/v1/rules", headers=_auth(client, admin_token)).json()
    assert all(r["rule_key"] != "dr-001" for r in listed)


def test_real_run_creates_rules(client, admin_token):
    r = client.post(
        "/api/v1/rules/bulk",
        json={"rules": [_rule("real-001"), _rule("real-002")], "dry_run": False},
        headers=_auth(client, admin_token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 2
    assert body["conflicts"] == 0
    for it in body["items"]:
        assert it["status"] == "created"
        assert it["rule_id"] is not None

    listed = client.get("/api/v1/rules", headers=_auth(client, admin_token)).json()
    keys = {r["rule_key"] for r in listed}
    assert "real-001" in keys and "real-002" in keys


def test_duplicate_within_payload_flagged(client, admin_token):
    """Same rule_key twice in one payload: both must be reported."""
    r = client.post(
        "/api/v1/rules/bulk",
        json={"rules": [_rule("dup-001"), _rule("dup-001")], "dry_run": True},
        headers=_auth(client, admin_token),
    )
    body = r.json()
    assert body["conflicts"] == 2
    for it in body["items"]:
        assert it["status"] == "would_conflict"
        assert "duplicate" in (it["error"] or "")


def test_real_run_with_existing_key_yields_conflict(client, admin_token):
    """A key that already exists in DB must come back as conflict, not 500."""
    client.post(
        "/api/v1/rules",
        json=_rule("pre-existing"),
        headers=_auth(client, admin_token),
    )
    r = client.post(
        "/api/v1/rules/bulk",
        json={
            "rules": [_rule("pre-existing"), _rule("brand-new")],
            "dry_run": False,
        },
        headers=_auth(client, admin_token),
    )
    body = r.json()
    assert body["conflicts"] == 1
    assert body["created"] == 1
    by_key = {it["rule_key"]: it for it in body["items"]}
    assert by_key["pre-existing"]["status"] == "conflict"
    assert by_key["brand-new"]["status"] == "created"


def test_admin_only(client, admin_token):
    """SAFETY: bulk import is creation × N — admin-only just like create_rule."""
    r = client.post(
        "/api/v1/rules/bulk",
        json={"rules": [_rule("z-001")], "dry_run": True},
    )
    assert r.status_code == 401


def test_max_500_rules_validated_by_pydantic(client, admin_token):
    """Pydantic max_length=500 enforces the upper bound."""
    payload = {"rules": [_rule(f"x-{i:04d}") for i in range(501)], "dry_run": True}
    r = client.post(
        "/api/v1/rules/bulk",
        json=payload,
        headers=_auth(client, admin_token),
    )
    assert r.status_code == 422


def test_min_1_rule_required(client, admin_token):
    """Empty payload is a 422 — explicit guard against accidental clear-all."""
    r = client.post(
        "/api/v1/rules/bulk",
        json={"rules": [], "dry_run": True},
        headers=_auth(client, admin_token),
    )
    assert r.status_code == 422


def test_real_run_writes_audit_summary(client, admin_token):
    import asyncio

    from waf_panel.repositories.deps import memory_audit_repo

    client.post(
        "/api/v1/rules/bulk",
        json={
            "rules": [_rule("audit-001"), _rule("audit-002")],
            "dry_run": False,
        },
        headers=_auth(client, admin_token),
    )
    repo = memory_audit_repo()
    assert repo is not None
    rows = asyncio.run(repo.recent(limit=20))
    actions = [r["action"] for r in rows]
    assert "rules.bulk_import" in actions
    summary = next(r for r in rows if r["action"] == "rules.bulk_import")
    assert summary["payload"]["created"] == 2
    assert summary["payload"]["total"] == 2


@pytest.mark.parametrize("dry_run", [True, False])
def test_response_shape_is_stable(client, admin_token, dry_run):
    r = client.post(
        "/api/v1/rules/bulk",
        json={"rules": [_rule(f"shape-{dry_run}")], "dry_run": dry_run},
        headers=_auth(client, admin_token),
    )
    body = r.json()
    assert {"dry_run", "total", "created", "conflicts", "items"} <= set(body.keys())
    for item in body["items"]:
        assert {"rule_key", "status"} <= set(item.keys())
