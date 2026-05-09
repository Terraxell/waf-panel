"""Database layer — SQLAlchemy 2.x async, PostgreSQL.

Public surface:
    - Base: declarative base for all models
    - models: ORM classes mirroring infra/postgres/init.sql
    - session: get_engine(), get_sessionmaker(), get_session() FastAPI dep
"""

from .base import Base
from .session import (
    SessionDep,
    dispose_engine,
    get_engine,
    get_session,
    get_sessionmaker,
)

__all__ = [
    "Base",
    "SessionDep",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
]
