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
    # WHY: defaults to True so tests can omit it; Sprint 0 contract.
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
            created_by=created_by,
        )
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
    """Sprint 11 — same key/value contract as the Pg version, dict-backed.

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


__all__ = [
    "InMemoryAuditRepo",
    "InMemoryMlConfigRepo",
    "InMemoryRulesRepo",
    "InMemoryUsersRepo",
    "_UserRow",
]
