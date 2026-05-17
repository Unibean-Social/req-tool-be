import uuid
from datetime import datetime

from pydantic import BaseModel


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
    description: str
    linked_feature_id: uuid.UUID | None = None


class ProjectRuleUpdate(BaseModel):
    description: str | None = None
    linked_feature_id: uuid.UUID | None = None


class ProjectRuleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    description: str
    linked_feature_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
