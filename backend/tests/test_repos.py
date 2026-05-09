"""Repository contract tests against the in-memory implementation.

WHY: the same protocol is meant to be implemented by both InMemory* and Pg*
     repositories. The Postgres path needs a live DB and is exercised in
     integration runs; here we lock the in-memory shape so service-layer
     tests can rely on it.
"""

from uuid import UUID

import pytest

from waf_panel.repositories.memory import (
    InMemoryAuditRepo,
    InMemoryRulesRepo,
    InMemoryUsersRepo,
    _UserRow,
)
from waf_panel.schemas import RuleCreate, RuleUpdate

ADMIN_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def users_repo() -> InMemoryUsersRepo:
    return InMemoryUsersRepo(
        seed=[
            _UserRow(
                id=ADMIN_ID,
                email="admin@example.com",
                password_hash="x",
                role="admin",
            )
        ]
    )


@pytest.fixture
def rules_repo() -> InMemoryRulesRepo:
    return InMemoryRulesRepo()


@pytest.fixture
def audit_repo() -> InMemoryAuditRepo:
    return InMemoryAuditRepo()


@pytest.fixture
def sample_payload() -> RuleCreate:
    return RuleCreate(
        rule_key="test-001",
        source="custom",
        severity=3,
        action="log",
        description="contract test rule",
        body="SecRule REQUEST_URI \"@contains test\" \"id:9999,deny\"",
        enabled=True,
    )


# ── users ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_users_lookup_is_case_insensitive(users_repo: InMemoryUsersRepo) -> None:
    found = await users_repo.by_email("ADMIN@example.com")
    assert found is not None
    assert found.id == ADMIN_ID


@pytest.mark.asyncio
async def test_users_unknown_returns_none(users_repo: InMemoryUsersRepo) -> None:
    assert await users_repo.by_email("ghost@example.com") is None


@pytest.mark.asyncio
async def test_users_touch_login_is_idempotent(users_repo: InMemoryUsersRepo) -> None:
    await users_repo.touch_login(ADMIN_ID)
    await users_repo.touch_login(ADMIN_ID)
    # WHY: in-memory repo records the latest timestamp; calling twice must not raise.


# ── rules ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rules_create_then_get(rules_repo: InMemoryRulesRepo, sample_payload: RuleCreate) -> None:
    created = await rules_repo.create(sample_payload, created_by=ADMIN_ID)
    assert created.rule_key == "test-001"
    fetched = await rules_repo.get(created.id)
    assert fetched == created


@pytest.mark.asyncio
async def test_rules_get_by_key(rules_repo: InMemoryRulesRepo, sample_payload: RuleCreate) -> None:
    await rules_repo.create(sample_payload, created_by=None)
    by_key = await rules_repo.get_by_key("test-001")
    assert by_key is not None
    assert by_key.rule_key == "test-001"
    assert await rules_repo.get_by_key("does-not-exist") is None


@pytest.mark.asyncio
async def test_rules_update_only_provided_fields(
    rules_repo: InMemoryRulesRepo, sample_payload: RuleCreate
) -> None:
    created = await rules_repo.create(sample_payload, created_by=None)
    patched = await rules_repo.update(created.id, RuleUpdate(action="block"))
    assert patched is not None
    assert patched.action == "block"
    # severity unchanged
    assert patched.severity == created.severity
    # updated_at advanced (or at least not before)
    assert patched.updated_at >= created.updated_at


@pytest.mark.asyncio
async def test_rules_delete_returns_bool(
    rules_repo: InMemoryRulesRepo, sample_payload: RuleCreate
) -> None:
    created = await rules_repo.create(sample_payload, created_by=None)
    assert await rules_repo.delete(created.id) is True
    assert await rules_repo.delete(created.id) is False
    assert await rules_repo.get(created.id) is None


# ── audit ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_records_in_order(audit_repo: InMemoryAuditRepo) -> None:
    await audit_repo.record(actor_id=ADMIN_ID, action="rule.create", target="rules:1")
    await audit_repo.record(actor_id=ADMIN_ID, action="rule.delete", target="rules:1")
    rows = await audit_repo.recent(limit=10)
    assert [r["action"] for r in rows] == ["rule.delete", "rule.create"]


@pytest.mark.asyncio
async def test_audit_payload_default_is_empty_dict(audit_repo: InMemoryAuditRepo) -> None:
    await audit_repo.record(actor_id=None, action="rule.delete", target="rules:1")
    rows = await audit_repo.recent()
    assert rows[0]["payload"] == {}
