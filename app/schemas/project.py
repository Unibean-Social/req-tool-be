import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    context: str | None = None
    problems: list[str] = []
    stakeholders: list[str] = []
    business_goals: list[str] = []
    business_flows: list[str] = []
    business_rules: list[str] = []
    proposed_solutions: list[str] = []


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    context: str | None = None
    problems: list[str] | None = None
    stakeholders: list[str] | None = None
    business_goals: list[str] | None = None
    business_flows: list[str] | None = None
    business_rules: list[str] | None = None
    proposed_solutions: list[str] | None = None


class ProjectResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    context: str | None = None
    problems: list[str] = []
    stakeholders: list[str] = []
    business_goals: list[str] = []
    business_flows: list[str] = []
    business_rules: list[str] = []
    proposed_solutions: list[str] = []
    created_at: datetime
