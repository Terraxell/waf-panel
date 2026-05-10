"""FastAPI dependency providers for repositories.

WHY: the API depends on a `Depends(get_*_repo)` callable, never on a class.
     `use_in_memory()` is the test-time switch that swaps the providers
     without monkey-patching.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from ..db.session import SessionDep, set_in_memory_mode
from .memory import (
    InMemoryAuditRepo,
    InMemoryMlConfigRepo,
    InMemoryRefreshFamiliesRepo,
    InMemoryRulesRepo,
    InMemoryUsersRepo,
    _UserRow,
)
from .pg import (
    PgAuditRepo,
    PgMlConfigRepo,
    PgRefreshFamiliesRepo,
    PgRulesRepo,
    PgUsersRepo,
)

_mem_users: InMemoryUsersRepo | None = None
_mem_rules: InMemoryRulesRepo | None = None
_mem_audit: InMemoryAuditRepo | None = None
_mem_ml_config: InMemoryMlConfigRepo | None = None
_mem_refresh: InMemoryRefreshFamiliesRepo | None = None
_in_memory_active: bool = False


def use_in_memory(*, seed_users: list[_UserRow] | None = None) -> None:
    """Switch dependency providers to in-memory implementations.

    SAFETY: tests only. In production this stays untouched.
    """
    global _mem_users, _mem_rules, _mem_audit, _mem_ml_config, _mem_refresh, _in_memory_active
    _mem_users = InMemoryUsersRepo(seed=seed_users)
    _mem_rules = InMemoryRulesRepo()
    _mem_audit = InMemoryAuditRepo()
    _mem_ml_config = InMemoryMlConfigRepo()
    _mem_refresh = InMemoryRefreshFamiliesRepo()
    _in_memory_active = True
    set_in_memory_mode(True)


def reset_in_memory() -> None:
    global _mem_users, _mem_rules, _mem_audit, _mem_ml_config, _mem_refresh, _in_memory_active
    _mem_users = _mem_rules = _mem_audit = _mem_ml_config = _mem_refresh = None
    _in_memory_active = False
    set_in_memory_mode(False)


def is_in_memory_active() -> bool:
    return _in_memory_active


def memory_audit_repo() -> InMemoryAuditRepo | None:
    """Test helper: read the in-memory audit log directly."""
    return _mem_audit


def memory_ml_config_repo() -> InMemoryMlConfigRepo | None:
    """Test helper: read the in-memory ml_config kv directly."""
    return _mem_ml_config


async def get_users_repo(session: SessionDep) -> Any:
    if _in_memory_active:
        assert _mem_users is not None
        return _mem_users
    assert session is not None
    return PgUsersRepo(session)


async def get_rules_repo(session: SessionDep) -> Any:
    if _in_memory_active:
        assert _mem_rules is not None
        return _mem_rules
    assert session is not None
    return PgRulesRepo(session)


async def get_audit_repo(session: SessionDep) -> Any:
    if _in_memory_active:
        assert _mem_audit is not None
        return _mem_audit
    assert session is not None
    return PgAuditRepo(session)


async def get_ml_config_repo(session: SessionDep) -> Any:
    if _in_memory_active:
        assert _mem_ml_config is not None
        return _mem_ml_config
    assert session is not None
    return PgMlConfigRepo(session)


async def get_refresh_families_repo(session: SessionDep) -> Any:
    if _in_memory_active:
        assert _mem_refresh is not None
        return _mem_refresh
    assert session is not None
    return PgRefreshFamiliesRepo(session)


UsersRepoDep = Annotated[Any, Depends(get_users_repo)]
RulesRepoDep = Annotated[Any, Depends(get_rules_repo)]
AuditRepoDep = Annotated[Any, Depends(get_audit_repo)]
MlConfigRepoDep = Annotated[Any, Depends(get_ml_config_repo)]
RefreshFamiliesRepoDep = Annotated[Any, Depends(get_refresh_families_repo)]


__all__ = [
    "AuditRepoDep",
    "MlConfigRepoDep",
    "RefreshFamiliesRepoDep",
    "RulesRepoDep",
    "UsersRepoDep",
    "get_audit_repo",
    "get_ml_config_repo",
    "get_refresh_families_repo",
    "get_rules_repo",
    "get_users_repo",
    "is_in_memory_active",
    "memory_audit_repo",
    "memory_ml_config_repo",
    "reset_in_memory",
    "use_in_memory",
]
