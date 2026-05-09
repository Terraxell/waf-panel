"""Repository protocols.

WHY: every endpoint depends on the protocol, never on a concrete class.
     This keeps the API decoupled from SQLAlchemy and lets tests inject the
     in-memory variant without spinning up a database.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from ..schemas import RuleCreate, RuleOut, RuleUpdate


class UserRecord(Protocol):
    """Minimal shape an auth flow needs from a user row."""

    id: UUID
    email: str
    password_hash: str
    role: str
    is_active: bool


class UsersRepo(Protocol):
    async def by_email(self, email: str) -> UserRecord | None: ...
    async def touch_login(self, user_id: UUID) -> None: ...


class RulesRepo(Protocol):
    async def list(self) -> list[RuleOut]: ...
    async def get(self, rule_id: UUID) -> RuleOut | None: ...
    async def get_by_key(self, rule_key: str) -> RuleOut | None: ...
    async def create(self, payload: RuleCreate, *, created_by: UUID | None) -> RuleOut: ...
    async def update(self, rule_id: UUID, patch: RuleUpdate) -> RuleOut | None: ...
    async def delete(self, rule_id: UUID) -> bool: ...


class AuditRepo(Protocol):
    async def record(
        self,
        *,
        actor_id: UUID | None,
        action: str,
        target: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]: ...


class MlConfigRepo(Protocol):
    """Sprint 11 — persistent ML settings (block-mode threshold etc.)."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, *, updated_by: UUID | None = None) -> None: ...


__all__ = ["AuditRepo", "MlConfigRepo", "RulesRepo", "UserRecord", "UsersRepo"]
