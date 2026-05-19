import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.project_business import RuleType


class ProjectGoalCreate(BaseModel):
    description: str
    order: int = 0


class ProjectGoalUpdate(BaseModel):
    description: str | None = None
    order: int | None = None


class ProjectGoalResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    description: str
    order: int
    created_at: datetime
    updated_at: datetime


# ── Rules ─────────────────────────────────────────────────────────────────────

class ProjectRuleCreate(BaseModel):
    rule_def: str
    type: RuleType
    is_dynamic: bool = False
    source: str | None = None


class ProjectRuleUpdate(BaseModel):
    rule_def: str | None = None
    type: RuleType | None = None
    is_dynamic: bool | None = None
    source: str | None = None


class ProjectRuleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    rule_def: str
    type: RuleType
    is_dynamic: bool
    source: str | None
    created_at: datetime
    updated_at: datetime


# ── Flow Actions ───────────────────────────────────────────────────────────────

class ProjectFlowActionCreate(BaseModel):
    order: int = 0
    description: str
    actor_id: uuid.UUID | None = None


class ProjectFlowActionUpdate(BaseModel):
    order: int | None = None
    description: str | None = None
    actor_id: uuid.UUID | None = None


class ProjectFlowActionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    flow_id: uuid.UUID
    actor_id: uuid.UUID | None
    order: int
    description: str
    rules: list[ProjectRuleResponse] = []
    created_at: datetime
    updated_at: datetime


# ── Flows ──────────────────────────────────────────────────────────────────────

class ProjectFlowCreate(BaseModel):
    code: str
    name: str
    description: str | None = None


class ProjectFlowUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None


class ProjectFlowResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    description: str | None
    actions: list[ProjectFlowActionResponse] = []
    created_at: datetime
    updated_at: datetime
