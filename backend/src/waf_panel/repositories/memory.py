"""In-memory repository implementation. Test-only; never imported in prod."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from ..schemas import RuleCreate, RuleOut, RuleUpdate

UTC = timezone.utc


@dataclass
class _UserRow:
    id: UUID
    email: str
    password_hash: str
    role: str
    # WHY: defaults to True so tests can omit it;  contract.
    is_active: bool = True


class InMemoryUsersRepo:
    def __init__(self, seed: list[_UserRow] | None = None) -> None:
        self._by_id: dict[UUID, _UserRow] = {u.id: u for u in (seed or [])}
        # WHY: Postgres uses CITEXT for the email column; mirror its
        #      case-insensitive lookup contract by lowercasing the keys.
        self._by_email: dict[str, UUID] = {u.email.lower(): u.id for u in (seed or [])}

    async def by_email(self, email: str) -> _UserRow | None:
        uid = self._by_email.get(email.lower())
        return self._by_id.get(uid) if uid else None

    async def by_id(self, user_id: UUID) -> _UserRow | None:
        return self._by_id.get(user_id)

    async def list_all(self) -> list[_UserRow]:
        # WHY sorted by id: deterministic for tests; PG version sorts
        # by created_at DESC, but the in-memory rows have no
        # created_at by design (kept dataclass tiny).
        return list(self._by_id.values())

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        role: str,
    ) -> _UserRow:
        row = _UserRow(
            id=uuid4(),
            email=email,
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        self._by_id[row.id] = row
        self._by_email[row.email.lower()] = row.id
        return row

    async def update_partial(
        self,
        user_id: UUID,
        *,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> _UserRow | None:
        row = self._by_id.get(user_id)
        if row is None:
            return None
        if role is not None:
            row.role = role
        if is_active is not None:
            row.is_active = is_active
        return row

    async def delete(self, user_id: UUID) -> bool:
        # Soft-delete -- match PG behaviour. The audit_log fixture in
        # tests has FK to users.id, so we never actually pop the row.
        row = self._by_id.get(user_id)
        if row is None:
            return False
        row.is_active = False
        return True

    async def touch_login(self, user_id: UUID) -> None:
        return  # no-op


class InMemoryRulesRepo:
    def __init__(self) -> None:
        self._rows: list[RuleOut] = []

    async def list(self) -> list[RuleOut]:
        return list(self._rows)

    async def get(self, rule_id: UUID) -> RuleOut | None:
        return next((r for r in self._rows if r.id == rule_id), None)

    async def get_by_key(self, rule_key: str) -> RuleOut | None:
        return next((r for r in self._rows if r.rule_key == rule_key), None)

    async def create(self, payload: RuleCreate, *, created_by: UUID | None) -> RuleOut:
        row = RuleOut(
            id=uuid4(),
            rule_key=payload.rule_key,
            source=payload.source,
            severity=payload.severity,
            action=payload.action,
            description=payload.description,
            body=payload.body,
            enabled=payload.enabled,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        # WHY: created_by is part of the create() signature so the
        # service layer can pass through the actor id, but RuleOut itself
        # does not carry it -- audit logging records the actor via
        # audit_repo.record(actor_id=...) instead. Keep the kwarg in the
        # signature for symmetry with PgRulesRepo.create.
        _ = created_by
        self._rows.append(row)
        return row

    async def update(self, rule_id: UUID, patch: RuleUpdate) -> RuleOut | None:
        for i, r in enumerate(self._rows):
            if r.id == rule_id:
                data = r.model_dump()
                changes = patch.model_dump(exclude_unset=True)
                data.update(changes)
                data["updated_at"] = datetime.now(UTC)
                self._rows[i] = RuleOut.model_validate(data)
                return self._rows[i]
        return None

    async def delete(self, rule_id: UUID) -> bool:
        for i, r in enumerate(self._rows):
            if r.id == rule_id:
                del self._rows[i]
                return True
        return False


class InMemoryAuditRepo:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    async def record(
        self,
        *,
        actor_id: UUID | None,
        action: str,
        target: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._rows.append({
            "ts": datetime.now(UTC),
            "actor_id": actor_id,
            "action": action,
            "target": target,
            "payload": payload or {},
        })

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(reversed(self._rows[-limit:]))


class InMemoryMlConfigRepo:
    """ — same key/value contract as the Pg version, dict-backed.

    WHY: keeps existing in-memory test fixtures simple. Production wiring
    goes through ``PgMlConfigRepo`` which actually writes to Postgres.
    """

    def __init__(self, seed: dict[str, str] | None = None) -> None:
        # SAFETY: seed the annotate-only default so a fresh in-memory test
        #         matches a freshly-migrated Postgres after init.sql.
        self._kv: dict[str, str] = dict(seed) if seed else {"ml_block_threshold": "1.0"}

    async def get(self, key: str) -> str | None:
        return self._kv.get(key)

    async def set(
        self, key: str, value: str, *, updated_by: UUID | None = None,  # noqa: ARG002
    ) -> None:
        self._kv[key] = value


@dataclass
class _RefreshFamilyRow:
    """In-memory mirror of RefreshTokenFamily ORM row."""
    id: UUID
    user_id: UUID
    generation: int = 0
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class InMemoryRefreshFamiliesRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, _RefreshFamilyRow] = {}

    async def by_id(self, family_id: UUID) -> _RefreshFamilyRow | None:
        return self._rows.get(family_id)

    async def create(self, *, user_id: UUID) -> _RefreshFamilyRow:
        fid = uuid4()
        row = _RefreshFamilyRow(id=fid, user_id=user_id, generation=0)
        self._rows[fid] = row
        return row

    async def bump_generation(self, family_id: UUID) -> _RefreshFamilyRow | None:
        row = self._rows.get(family_id)
        if row is None or row.revoked_at is not None:
            return None
        row.generation += 1
        row.last_used_at = datetime.now(UTC)
        return row

    async def revoke(self, family_id: UUID) -> None:
        row = self._rows.get(family_id)
        if row is not None:
            row.revoked_at = datetime.now(UTC)


__all__ = [
    "InMemoryAuditRepo",
    "InMemoryMlConfigRepo",
    "InMemoryRefreshFamiliesRepo",
    "InMemoryRulesRepo",
    "InMemoryUsersRepo",
    "_RefreshFamilyRow",
    "_UserRow",
]
