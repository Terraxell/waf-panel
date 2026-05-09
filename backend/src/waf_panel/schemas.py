"""Pydantic models — wire schemas only.

WHY: Pydantic models are the only contract between the panel and any client.
     They double as the OpenAPI schema, which the supervisor sees as
     `/docs` during defence.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ── auth ────────────────────────────────────────────────────────────


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds


class CurrentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: Literal["admin", "analyst", "viewer"]
    is_active: bool


# ── rules ───────────────────────────────────────────────────────────

RuleSource = Literal["crs", "custom", "ml"]
RuleAction = Literal["block", "log", "challenge"]


class RuleBase(BaseModel):
    rule_key: str = Field(min_length=1, max_length=64)
    source: RuleSource
    severity: int = Field(ge=1, le=5)
    action: RuleAction
    description: str = Field(min_length=1, max_length=500)
    body: str
    enabled: bool = True


class RuleCreate(RuleBase):
    pass


class RuleUpdate(BaseModel):
    severity: int | None = Field(default=None, ge=1, le=5)
    action: RuleAction | None = None
    description: str | None = Field(default=None, max_length=500)
    body: str | None = None
    enabled: bool | None = None


class RuleOut(RuleBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime


# ── incidents ───────────────────────────────────────────────────────


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ts: datetime
    rule_id: UUID | None
    model_id: UUID | None
    decision: RuleAction
    severity: int
    score_ml: float | None
    ip: str | None
    method: str | None
    path: str | None


# ── health ──────────────────────────────────────────────────────────


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    components: dict[str, str]
