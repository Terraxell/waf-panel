"""Refresh-token families — ADR-0015.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-26

WHY: refresh-token rotation needs per-session server-side state so a
replay (the same generation presented twice) is detectable. This
table is the minimum -- one row per active session, generation
counter, revoked_at for theft response.

The auth endpoints write here on /login (insert), /refresh
(generation bump or revoke-on-replay), and /logout (revoke). Reads
are O(1) via the PK uuid.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_token_families",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # WHY index on (user_id) only: lookups by id are PK; lookups by
    # user (for "list active sessions" UI in a follow-up ADR) are the
    # other access pattern.
    op.create_index(
        "ix_refresh_token_families_user_id",
        "refresh_token_families",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_refresh_token_families_user_id",
        table_name="refresh_token_families",
    )
    op.drop_table("refresh_token_families")
