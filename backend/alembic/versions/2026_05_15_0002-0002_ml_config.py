"""ml_config — operator-controllable ML settings.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-15

WHY: Sprint 11 — drop the in-memory threshold dict from Sprint 10 and
persist `ml_block_threshold` (and future settings) in Postgres. Same
idempotency pattern as 0001: `_table_missing()` gate so the migration
re-applies safely against a volume that already ran init.sql.

NOTE: offline mode cannot inspect tables; it emits the CREATE
unconditionally. The seed row goes in the same transaction so a fresh
deployment starts in annotate-only mode (`value_text='1.0'`) without
the operator having to touch anything.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_missing(name: str) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    return name not in inspect(bind).get_table_names()


def upgrade() -> None:
    if _table_missing("ml_config"):
        op.create_table(
            "ml_config",
            sa.Column("key", sa.String(length=64), primary_key=True),
            sa.Column("value_text", sa.Text(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        # WHY: bake in the annotate-only default so a fresh deploy is safe.
        op.execute(
            "INSERT INTO ml_config (key, value_text) VALUES "
            "('ml_block_threshold', '1.0') "
            "ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    op.drop_table("ml_config")
