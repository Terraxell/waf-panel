"""Alembic environment — async-aware, single source of truth for DSN.

Run from the backend/ folder:
    alembic upgrade head      # apply all migrations
    alembic revision --autogenerate -m "describe change"
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# WHY: keep imports lazy so a missing model file doesn't block `alembic --help`.
from waf_panel.config import get_settings  # noqa: E402
from waf_panel.db.base import Base  # noqa: E402
from waf_panel.db import models  # noqa: F401, E402  -- side-effect: register tables

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_dsn() -> str:
    # Alembic's offline mode wants a sync URL.
    return get_settings().postgres_dsn.replace("postgresql+psycopg", "postgresql+psycopg")


def run_migrations_offline() -> None:
    """Generate SQL into stdout without connecting."""
    context.configure(
        url=_sync_dsn(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _sync_dsn()
    connectable = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
