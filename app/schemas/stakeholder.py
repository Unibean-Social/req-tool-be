import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.stakeholder import InfluenceLevel


class StakeholderCreateRequest(BaseModel):
    name: str
    role: str | None = None
    impact_area: str | None = None
    influence_level: InfluenceLevel = InfluenceLevel.medium
    notes: str | None = None
    is_business_actor: bool = False


class StakeholderUpdateRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    impact_area: str | None = None
    influence_level: InfluenceLevel | None = None
    notes: str | None = None
    is_business_actor: bool | None = None


class StakeholderResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    role: str | None
    impact_area: str | None
    influence_level: InfluenceLevel
    notes: str | None
    is_business_actor: bool
    created_at: datetime
    updated_at: datetime
