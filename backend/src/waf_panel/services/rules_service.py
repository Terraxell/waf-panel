"""Rules service: CRUD + audit, transaction-friendly.

WHY: every mutation produces an audit row. Both writes go through the same
     repositories, which share the same session in production, so they
     commit or roll back together.
"""

from __future__ import annotations

from uuid import UUID

from ..repositories.base import AuditRepo, RulesRepo
from ..schemas import RuleCreate, RuleOut, RuleUpdate


class RuleConflict(Exception):
    """rule_key already in use."""


class RuleNotFound(Exception):
    pass


class RulesService:
    def __init__(self, rules: RulesRepo, audit: AuditRepo) -> None:
        self._rules = rules
        self._audit = audit

    async def list(self) -> list[RuleOut]:
        return await self._rules.list()

    async def get(self, rule_id: UUID) -> RuleOut:
        rule = await self._rules.get(rule_id)
        if rule is None:
            raise RuleNotFound(str(rule_id))
        return rule

    async def create(self, payload: RuleCreate, *, actor_id: UUID | None) -> RuleOut:
        existing = await self._rules.get_by_key(payload.rule_key)
        if existing is not None:
            raise RuleConflict(payload.rule_key)
        rule = await self._rules.create(payload, created_by=actor_id)
        await self._audit.record(
            actor_id=actor_id,
            action="rule.create",
            target=f"rules:{rule.id}",
            payload={"rule_key": rule.rule_key, "source": rule.source, "action": rule.action},
        )
        return rule

    async def update(self, rule_id: UUID, patch: RuleUpdate, *, actor_id: UUID | None) -> RuleOut:
        rule = await self._rules.update(rule_id, patch)
        if rule is None:
            raise RuleNotFound(str(rule_id))
        await self._audit.record(
            actor_id=actor_id,
            action="rule.update",
            target=f"rules:{rule_id}",
            payload=patch.model_dump(exclude_none=True),
        )
        return rule

    async def delete(self, rule_id: UUID, *, actor_id: UUID | None) -> None:
        ok = await self._rules.delete(rule_id)
        if not ok:
            raise RuleNotFound(str(rule_id))
        await self._audit.record(
            actor_id=actor_id,
            action="rule.delete",
            target=f"rules:{rule_id}",
            payload={},
        )


__all__ = ["RuleConflict", "RuleNotFound", "RulesService"]
