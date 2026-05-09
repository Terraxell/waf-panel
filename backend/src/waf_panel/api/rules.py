"""Rules CRUD — DB-backed via RulesService."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..repositories.deps import AuditRepoDep, RulesRepoDep
from ..schemas import CurrentUser, RuleCreate, RuleOut, RuleUpdate
from ..services.rules_service import RuleConflict, RuleNotFound, RulesService
from .auth import require_role

router = APIRouter(prefix="/rules", tags=["rules"])


def _service(rules, audit) -> RulesService:
    return RulesService(rules=rules, audit=audit)


@router.get("", response_model=list[RuleOut])
async def list_rules(
    rules: RulesRepoDep,
    audit: AuditRepoDep,
    _: Annotated[CurrentUser, Depends(require_role("admin", "analyst", "viewer"))],
) -> list[RuleOut]:
    return await _service(rules, audit).list()


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: RuleCreate,
    rules: RulesRepoDep,
    audit: AuditRepoDep,
    user: Annotated[CurrentUser, Depends(require_role("admin", "analyst"))],
) -> RuleOut:
    try:
        return await _service(rules, audit).create(payload, actor_id=user.id)
    except RuleConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "rule_key already exists") from exc


@router.get("/{rule_id}", response_model=RuleOut)
async def get_rule(
    rule_id: UUID,
    rules: RulesRepoDep,
    audit: AuditRepoDep,
    _: Annotated[CurrentUser, Depends(require_role("admin", "analyst", "viewer"))],
) -> RuleOut:
    try:
        return await _service(rules, audit).get(rule_id)
    except RuleNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rule not found") from exc


@router.put("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: UUID,
    patch: RuleUpdate,
    rules: RulesRepoDep,
    audit: AuditRepoDep,
    user: Annotated[CurrentUser, Depends(require_role("admin", "analyst"))],
) -> RuleOut:
    try:
        return await _service(rules, audit).update(rule_id, patch, actor_id=user.id)
    except RuleNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rule not found") from exc


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: UUID,
    rules: RulesRepoDep,
    audit: AuditRepoDep,
    user: Annotated[CurrentUser, Depends(require_role("admin"))],
) -> None:
    try:
        await _service(rules, audit).delete(rule_id, actor_id=user.id)
    except RuleNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rule not found") from exc


# ── Bulk import (Sprint 13, audit C-list item 18a) ──────────────────────

from pydantic import BaseModel, Field


class BulkImportRequest(BaseModel):
    """List of new rules + dry-run flag.

    SAFETY: dry_run defaults to True so a panel slipping past Auth
    without proper UI confirmation can't accidentally create dozens of
    rules. The frontend has to send `dry_run: false` explicitly.
    """
    rules: list[RuleCreate] = Field(min_length=1, max_length=500)
    dry_run: bool = True


class BulkImportItemResult(BaseModel):
    rule_key: str
    status: str  # "created" | "conflict" | "would_create" | "would_conflict"
    rule_id: UUID | None = None
    error: str | None = None


class BulkImportResponse(BaseModel):
    dry_run: bool
    total: int
    created: int
    conflicts: int
    items: list[BulkImportItemResult]


@router.post("/bulk", response_model=BulkImportResponse)
async def bulk_import(
    payload: BulkImportRequest,
    rules: RulesRepoDep,
    audit: AuditRepoDep,
    user: Annotated[CurrentUser, Depends(require_role("admin"))],
) -> BulkImportResponse:
    """Create up to 500 rules in one call. dry_run=true validates only."""
    svc = _service(rules, audit)
    items: list[BulkImportItemResult] = []
    created = 0
    conflicts = 0

    # WHY: pre-scan for duplicate rule_keys *within the same payload* —
    # the DB unique-index would catch them but the error UX is worse.
    seen: set[str] = set()
    duplicates_in_payload: set[str] = set()
    for r in payload.rules:
        if r.rule_key in seen:
            duplicates_in_payload.add(r.rule_key)
        seen.add(r.rule_key)

    for spec in payload.rules:
        if spec.rule_key in duplicates_in_payload:
            items.append(BulkImportItemResult(
                rule_key=spec.rule_key,
                status="would_conflict" if payload.dry_run else "conflict",
                error="duplicate within payload",
            ))
            conflicts += 1
            continue

        existing = await rules.get_by_key(spec.rule_key)
        if existing is not None:
            items.append(BulkImportItemResult(
                rule_key=spec.rule_key,
                status="would_conflict" if payload.dry_run else "conflict",
                error="rule_key exists",
            ))
            conflicts += 1
            continue

        if payload.dry_run:
            items.append(BulkImportItemResult(
                rule_key=spec.rule_key,
                status="would_create",
            ))
            created += 1
            continue

        try:
            row = await svc.create(spec, actor_id=user.id)
            items.append(BulkImportItemResult(
                rule_key=spec.rule_key,
                status="created",
                rule_id=row.id,
            ))
            created += 1
        except RuleConflict as e:
            # Race-condition fallback — another caller created this key
            # between the check above and the insert. Rare but possible.
            items.append(BulkImportItemResult(
                rule_key=spec.rule_key,
                status="conflict",
                error=str(e),
            ))
            conflicts += 1

    if not payload.dry_run:
        await audit.record(
            actor_id=user.id,
            action="rules.bulk_import",
            target="rules",
            payload={"created": created, "conflicts": conflicts, "total": len(payload.rules)},
        )

    return BulkImportResponse(
        dry_run=payload.dry_run,
        total=len(payload.rules),
        created=created,
        conflicts=conflicts,
        items=items,
    )
