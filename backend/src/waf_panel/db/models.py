"""ORM models — one-to-one with infra/postgres/init.sql.

WHY: keeping the SQLAlchemy metadata as a faithful mirror of the bootstrap
     SQL means alembic can autogenerate migrations cleanly and the team has
     a single source of truth for column types.
NOTE: server-side defaults (`gen_random_uuid()`, `now()`) are declared with
      `text()` so the database — not Python — picks the value. This makes
      INSERTs cheaper and keeps clocks consistent across processes.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# WHY: PostgreSQL CITEXT lives in an extension. We expose it as a TEXT-typed
#      column on the ORM side; the DB enforces the case-insensitive uniqueness.
EmailColumn = String(320)


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(EmailColumn, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'analyst', 'viewer')", name="users_role_check"),
    )


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    rule_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    creator: Mapped[User | None] = relationship("User", lazy="joined", foreign_keys=[created_by])

    __table_args__ = (
        CheckConstraint("source IN ('crs', 'custom', 'ml')", name="rules_source_check"),
        CheckConstraint("severity BETWEEN 1 AND 5", name="rules_severity_check"),
        CheckConstraint("action IN ('block', 'log', 'challenge')", name="rules_action_check"),
        Index("rules_source_idx", "source"),
        Index("rules_enabled_idx", "enabled"),
    )


class MLModel(Base):
    """Reserved for the future Postgres-backed model registry.

    WHY this class exists despite no runtime reads: the table is in the
    0001 schema baseline (already in every deployed database) and the
    `incidents.model_id` FK depends on it. The current ML path reads
    model metadata from the joblib registry under ``ml/models/active/``
    and ``ml_service`` carries its own ``/healthz.model_loaded``
    signal -- both bypass this table. A planned follow-up (ADR-0007
    appendix) wires the Pg row in on every promote so the panel can
    display "active model = vXXX" without scraping the filesystem.

    Removing the class would orphan the FK from ``incidents`` and
    require a migration that drops production tables; the carrying
    cost is ~10 lines, so we keep the contract.
    """
    __tablename__ = "ml_models"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    algo: Mapped[str] = mapped_column(String(64), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Incident(Base):
    """Reserved for the planned incident-detail endpoint.

    WHY this class exists despite no runtime reads: the
    ``GET /api/v1/incidents`` endpoint reads from ClickHouse
    ``traffic_log`` (cheap, denormalised, OLAP-friendly). The
    Postgres ``incidents`` table is the OLTP side -- a future
    incident-detail view that needs full payload + ML-score
    breakdown + per-incident actions (the audit C-list mentions
    this) will INSERT here from the request path and SELECT here
    from a detail endpoint. Removing the class today would orphan
    the schema baseline already deployed, so we keep the ORM
    contract aligned with the migration.
    """
    __tablename__ = "incidents"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("rules.id", ondelete="SET NULL")
    )
    model_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ml_models.id", ondelete="SET NULL")
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    score_ml: Mapped[float | None] = mapped_column()
    ip: Mapped[str | None] = mapped_column(INET)
    method: Mapped[str | None] = mapped_column(String(16))
    path: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "decision IN ('block', 'log', 'challenge')", name="incidents_decision_check"
        ),
        CheckConstraint("severity BETWEEN 1 AND 5", name="incidents_severity_check"),
        Index("incidents_ts_idx", "ts"),
        Index("incidents_ip_idx", "ip"),
        Index("incidents_dec_idx", "decision"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        Index("audit_log_ts_idx", "ts"),
        Index("audit_log_actor_idx", "actor_id"),
    )


class MlConfig(Base):
    """ — one row per operator-controllable ML setting.

    WHY:  stored the block-mode threshold in process memory;
    multi-replica gateways need persistence and an audit trail. This
    table is intentionally generic key/value so future settings (drift
    cadence, alert routing) reuse the same plumbing.

    SAFETY: ``value_text`` is canonical. Numeric / bool consumers parse
    it themselves so we don't have a typed-column zoo every new setting.
    """

    __tablename__ = "ml_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
    )




class RefreshTokenFamily(Base):
    """ADR-0015: one row per active refresh-token session.

    Generation counter detects replay: a refresh JWT carries
    ``family_id`` + ``generation`` claims; the server bumps generation
    on rotation. Presenting an older generation means the token was
    reused / stolen → revoke the family by setting ``revoked_at``.
    """
    __tablename__ = "refresh_token_families"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# WHY __all__ at the bottom: lets all classes (including
# RefreshTokenFamily added in 0004) be in scope when the export list is
# evaluated. Earlier the list lived above the new class, so a
# `from .db.models import *` (none today, but a future ADR may want it)
# would silently drop RefreshTokenFamily.
__all__ = [
    "AuditLog",
    "Incident",
    "MLModel",
    "MlConfig",
    "RefreshTokenFamily",
    "Rule",
    "User",
]
