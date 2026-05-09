"""initial schema — mirrors infra/postgres/init.sql exactly.

Revision ID: 0001
Revises:
Create Date: 2026-05-08

WHY: this revision matches the bootstrap SQL line-for-line so a fresh
     volume created from init.sql is functionally equivalent to one
     migrated from scratch. The migration is idempotent — every
     create_table is gated on a "does not exist" check, so it can be
     applied to a volume already initialised via init.sql.
NOTE: offline mode cannot inspect tables (mock connection), so it always
     emits all CREATE statements.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_missing(name: str) -> bool:
    # WHY: in offline mode (`alembic upgrade head --sql`) we can't query
    #      the DB, so always emit the CREATE — the rendered SQL is for
    #      review on a fresh DB anyway.
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    return name not in inspect(bind).get_table_names()


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    if _table_missing("users"):
        op.create_table(
            "users",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("email", sa.String(320), nullable=False, unique=True),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("last_login_at", sa.DateTime(timezone=True)),
            sa.CheckConstraint("role IN ('admin', 'analyst', 'viewer')", name="users_role_check"),
        )

    if _table_missing("rules"):
        op.create_table(
            "rules",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("rule_key", sa.String(64), nullable=False, unique=True),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column("severity", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(16), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
            sa.Column("created_by", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.CheckConstraint("source IN ('crs', 'custom', 'ml')", name="rules_source_check"),
            sa.CheckConstraint("severity BETWEEN 1 AND 5", name="rules_severity_check"),
            sa.CheckConstraint("action IN ('block', 'log', 'challenge')", name="rules_action_check"),
        )
        op.create_index("rules_source_idx", "rules", ["source"])
        op.create_index("rules_enabled_idx", "rules", ["enabled"])

    if _table_missing("ml_models"):
        op.create_table(
            "ml_models",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("version", sa.String(64), nullable=False, unique=True),
            sa.Column("algo", sa.String(64), nullable=False),
            sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("dataset", sa.Text(), nullable=False),
            sa.Column("metrics", postgresql.JSONB(), nullable=False),
            sa.Column("artifact_path", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ml_models_active_uniq "
            "ON ml_models((TRUE)) WHERE is_active"
        )

    if _table_missing("incidents"):
        op.create_table(
            "incidents",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("request_id", sa.Text(), nullable=False),
            sa.Column("rule_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("rules.id", ondelete="SET NULL")),
            sa.Column("model_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("ml_models.id", ondelete="SET NULL")),
            sa.Column("decision", sa.String(16), nullable=False),
            sa.Column("severity", sa.Integer(), nullable=False),
            sa.Column("score_ml", sa.Float()),
            sa.Column("ip", postgresql.INET()),
            sa.Column("method", sa.String(16)),
            sa.Column("path", sa.Text()),
            sa.Column("payload", postgresql.JSONB()),
            sa.CheckConstraint("decision IN ('block', 'log', 'challenge')",
                               name="incidents_decision_check"),
            sa.CheckConstraint("severity BETWEEN 1 AND 5", name="incidents_severity_check"),
        )
        op.create_index("incidents_ts_idx", "incidents", ["ts"])
        op.create_index("incidents_ip_idx", "incidents", ["ip"])
        op.create_index("incidents_dec_idx", "incidents", ["decision"])

    if _table_missing("audit_log"):
        op.create_table(
            "audit_log",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("target", sa.String(128), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False,
                      server_default=sa.text("'{}'::jsonb")),
        )
        op.create_index("audit_log_ts_idx", "audit_log", ["ts"])
        op.create_index("audit_log_actor_idx", "audit_log", ["actor_id"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS audit_log_actor_idx")
    op.execute("DROP INDEX IF EXISTS audit_log_ts_idx")
    op.execute("DROP TABLE IF EXISTS audit_log")

    op.execute("DROP INDEX IF EXISTS incidents_dec_idx")
    op.execute("DROP INDEX IF EXISTS incidents_ip_idx")
    op.execute("DROP INDEX IF EXISTS incidents_ts_idx")
    op.execute("DROP TABLE IF EXISTS incidents")

    op.execute("DROP INDEX IF EXISTS ml_models_active_uniq")
    op.execute("DROP TABLE IF EXISTS ml_models")

    op.execute("DROP INDEX IF EXISTS rules_enabled_idx")
    op.execute("DROP INDEX IF EXISTS rules_source_idx")
    op.execute("DROP TABLE IF EXISTS rules")

    op.execute("DROP TABLE IF EXISTS users")
