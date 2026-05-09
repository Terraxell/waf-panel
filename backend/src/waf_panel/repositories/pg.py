"""PostgreSQL implementations.

WHY: kept thin — they wrap SQLAlchemy queries and translate ORM rows to the
     wire schemas defined in `waf_panel.schemas`. The service layer is the
     one that decides "create vs reject duplicate" etc.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditLog, MlConfig, Rule, User
from ..schemas import RuleCreate, RuleOut, RuleUpdate

UTC = timezone.utc


def _to_rule_out(row: Rule) -> RuleOut:
    return RuleOut.model_validate(row)


class PgUsersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def touch_login(self, user_id: UUID) -> None:
        stmt = update(User).where(User.id == user_id).values(last_login_at=datetime.now(UTC))
        await self._s.execute(stmt)


class PgRulesRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list(self) -> list[RuleOut]:
        rows = (await self._s.execute(select(Rule))).scalars().all()
        return [_to_rule_out(r) for r in rows]

    async def get(self, rule_id: UUID) -> RuleOut | None:
        row = (await self._s.execute(select(Rule).where(Rule.id == rule_id))).scalar_one_or_none()
        return _to_rule_out(row) if row else None

    async def get_by_key(self, rule_key: str) -> RuleOut | None:
        row = (
            await self._s.execute(select(Rule).where(Rule.rule_key == rule_key))
        ).scalar_one_or_none()
        return _to_rule_out(row) if row else None

    async def create(self, payload: RuleCreate, *, created_by: UUID | None) -> RuleOut:
        row = Rule(**payload.model_dump(), created_by=created_by)
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _to_rule_out(row)

    async def update(self, rule_id: UUID, patch: RuleUpdate) -> RuleOut | None:
        row = (
            await self._s.execute(select(Rule).where(Rule.id == rule_id))
        ).scalar_one_or_none()
        if row is None:
            return None
        for k, v in patch.model_dump(exclude_none=True).items():
            setattr(row, k, v)
        row.updated_at = datetime.now(UTC)
        await self._s.flush()
        await self._s.refresh(row)
        return _to_rule_out(row)

    async def delete(self, rule_id: UUID) -> bool:
        row = (
            await self._s.execute(select(Rule).where(Rule.id == rule_id))
        ).scalar_one_or_none()
        if row is None:
            return False
        await self._s.delete(row)
        return True


class PgAuditRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def record(
        self,
        *,
        actor_id: UUID | None,
        action: str,
        target: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._s.add(AuditLog(
            actor_id=actor_id,
            action=action,
            target=target,
            payload=payload or {},
        ))

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        stmt = select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit)
        rows = (await self._s.execute(stmt)).scalars().all()
        return [
            {
                "ts": r.ts,
                "actor_id": r.actor_id,
                "action": r.action,
                "target": r.target,
                "payload": r.payload,
            }
            for r in rows
        ]


class PgMlConfigRepo:
    """Postgres-backed implementation of ``MlConfigRepo``.

    Sprint 11 — replaces the Sprint-10 in-process dict. Single key/value
    table; the threshold endpoint reads on every GET (cheap; one row),
    writes via ``ON CONFLICT (key) DO UPDATE`` for atomic upsert.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, key: str) -> str | None:
        stmt = select(MlConfig.value_text).where(MlConfig.key == key)
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def set(
        self, key: str, value: str, *, updated_by: UUID | None = None,
    ) -> None:
        # WHY: ``pg_insert`` gives us a portable upsert. ``updated_at`` is
        #      refreshed via the column's NOT NULL DEFAULT on conflict —
        #      we have to set it explicitly because DO UPDATE doesn't
        #      re-evaluate ``server_default``.
        stmt = pg_insert(MlConfig).values(
            key=key, value_text=value, updated_by=updated_by,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "value_text": value,
                "updated_at": datetime.now(UTC),
                "updated_by": updated_by,
            },
        )
        await self._s.execute(stmt)
        await self._s.commit()


__all__ = ["PgAuditRepo", "PgMlConfigRepo", "PgRulesRepo", "PgUsersRepo"]
