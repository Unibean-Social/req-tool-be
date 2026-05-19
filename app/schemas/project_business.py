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


class ProjectFlowCreate(BaseModel):
    title: str
    description: str | None = None
    order: int = 0


class ProjectFlowUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    order: int | None = None


class ProjectFlowResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str | None
    order: int
    created_at: datetime
    updated_at: datetime


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
