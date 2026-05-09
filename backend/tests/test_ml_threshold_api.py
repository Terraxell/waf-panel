"""ML threshold endpoint — RBAC, validation, audit log."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_threshold():
    """Snap threshold back to 1.0 between tests so cases stay independent."""
    from waf_panel.api.ml import _reset_threshold_for_tests

    _reset_threshold_for_tests()
    yield
    _reset_threshold_for_tests()


def test_get_threshold_default_is_1_for_annotate_only(client, admin_token):
    r = client.get(
        "/api/v1/ml/threshold",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["value"] == 1.0


def test_get_threshold_requires_auth(client):
    r = client.get("/api/v1/ml/threshold")
    assert r.status_code == 401


def test_put_threshold_admin_can_update(client, admin_token):
    r = client.put(
        "/api/v1/ml/threshold",
        json={"value": 0.93},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["value"] == pytest.approx(0.93)

    # GET should now reflect the new value.
    r2 = client.get(
        "/api/v1/ml/threshold",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.json()["value"] == pytest.approx(0.93)


def test_put_threshold_rejects_out_of_range(client, admin_token):
    """Pydantic ge=0.0, le=1.0 — 422 on bad input, value stays clean."""
    bad = client.put(
        "/api/v1/ml/threshold",
        json={"value": 1.5},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert bad.status_code == 422
    # And the read-side stayed at the default.
    cur = client.get(
        "/api/v1/ml/threshold",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cur.json()["value"] == 1.0


def test_put_threshold_rejects_unknown_fields(client, admin_token):
    """`extra=forbid` keeps the schema honest."""
    r = client.put(
        "/api/v1/ml/threshold",
        json={"value": 0.8, "rogue": "ignored"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 422


def test_put_threshold_records_audit_row(client, admin_token):
    from waf_panel.repositories.deps import memory_audit_repo

    client.put(
        "/api/v1/ml/threshold",
        json={"value": 0.85},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    repo = memory_audit_repo()
    assert repo is not None
    rows = pytest.run = None
    # Use the same async accessor the API uses.
    import asyncio
    rows = asyncio.run(repo.recent(limit=10))
    actions = [r["action"] for r in rows]
    assert "ml.threshold.update" in actions
    payload = next(r["payload"] for r in rows if r["action"] == "ml.threshold.update")
    assert payload["prev"] == 1.0
    assert payload["new"] == pytest.approx(0.85)


def test_put_threshold_rollback_to_one_zero(client, admin_token):
    """Kill-switch path: setting value back to 1.0 disables block-mode instantly."""
    client.put(
        "/api/v1/ml/threshold",
        json={"value": 0.7},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    r = client.put(
        "/api/v1/ml/threshold",
        json={"value": 1.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["value"] == 1.0
