"""Async engine, session factory, FastAPI dependency.

WHY: every AsyncSession in the codebase comes from `get_session`. That is the
     only way to guarantee one transaction per request, with rollback on error
     and commit on a clean exit.
NOTE: when the in-memory repositories are active (tests), `get_session`
      yields None so the dependency graph is satisfied without ever opening
      a database connection. In-memory repos accept a None session.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_in_memory: bool = False


def set_in_memory_mode(active: bool) -> None:
    """Test hook: short-circuit get_session when the in-memory repos are on."""
    global _in_memory
    _in_memory = active


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        dsn = get_settings().postgres_dsn
        _engine = create_async_engine(dsn, pool_pre_ping=True, future=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession | None]:
    """FastAPI dependency yielding a session, or None in test mode."""
    if _in_memory:
        yield None
        return
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession | None, Depends(get_session)]


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


__all__ = [
    "SessionDep",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "set_in_memory_mode",
]
