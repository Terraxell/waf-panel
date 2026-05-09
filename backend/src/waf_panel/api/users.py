"""User management endpoints — task #123.

WHY: until now there is exactly one admin row, seeded by alembic 0003.
Adding a second user means hand-editing the DB. This module exposes
admin-only CRUD so an operator can onboard analysts/viewers from the
panel.

Five endpoints, all behind ``require_role('admin')``:
    GET    /users           — list (newest first)
    POST   /users           — create with email + role + password
    PATCH  /users/{id}      — update role and/or is_active
    DELETE /users/{id}      — soft-delete (sets is_active=False)
    -- self-modification is rejected on PATCH/DELETE so an admin can't
       lock themselves out by accident.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..repositories.deps import AuditRepoDep, UsersRepoDep
from ..schemas import CurrentUser, UserCreateIn, UserOut, UserUpdateIn
from ..security import hash_password
from .auth import require_role

router = APIRouter(prefix="/users", tags=["users"])

_ADMIN_ONLY = require_role("admin")


def _to_out(row: object) -> UserOut:
    """ORM row OR in-memory ``_UserRow`` -> wire shape. We accept both
    because the test fixture uses the dataclass; production uses the
    SQLAlchemy model. UserOut.from_attributes handles either as long
    as the attribute names line up."""
    return UserOut.model_validate(row)


@router.get("", response_model=list[UserOut])
async def list_users(
    users: UsersRepoDep,
    _: Annotated[CurrentUser, Depends(_ADMIN_ONLY)],
) -> list[UserOut]:
    rows = await users.list_all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateIn,
    users: UsersRepoDep,
    audit: AuditRepoDep,
    actor: Annotated[CurrentUser, Depends(_ADMIN_ONLY)],
) -> UserOut:
    if await users.by_email(str(payload.email)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "user with this email already exists",
        )
    row = await users.create(
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    await audit.record(
        actor_id=actor.id,
        action="user.create",
        target=str(row.id),
        payload={"email": row.email, "role": row.role},
    )
    return _to_out(row)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    patch: UserUpdateIn,
    users: UsersRepoDep,
    audit: AuditRepoDep,
    actor: Annotated[CurrentUser, Depends(_ADMIN_ONLY)],
) -> UserOut:
    if user_id == actor.id:
        # SAFETY: an admin who downgraded their own role would be locked
        # out of the very endpoint they need to fix the mistake. Refuse.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "cannot modify your own account; use a sibling admin",
        )
    row = await users.update_partial(
        user_id,
        role=patch.role,
        is_active=patch.is_active,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    await audit.record(
        actor_id=actor.id,
        action="user.update",
        target=str(user_id),
        payload=patch.model_dump(exclude_unset=True),
    )
    return _to_out(row)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    users: UsersRepoDep,
    audit: AuditRepoDep,
    actor: Annotated[CurrentUser, Depends(_ADMIN_ONLY)],
) -> None:
    if user_id == actor.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "cannot delete your own account; use a sibling admin",
        )
    ok = await users.delete(user_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    await audit.record(
        actor_id=actor.id,
        action="user.delete",
        target=str(user_id),
        payload={},
    )


__all__ = ["router"]
