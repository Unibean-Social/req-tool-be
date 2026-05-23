import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.stakeholder import ActorType, InfluenceLevel


class StakeholderCreateRequest(BaseModel):
    name: str
    role: str | None = None
    impact_area: str | None = None
    influence_level: InfluenceLevel = InfluenceLevel.medium
    notes: str | None = None
    actor_type: ActorType = ActorType.none
    system_description: str | None = None


class StakeholderUpdateRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    impact_area: str | None = None
    influence_level: InfluenceLevel | None = None
    notes: str | None = None
    actor_type: ActorType | None = None
    system_description: str | None = None


class StakeholderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    role: str | None
    impact_area: str | None
    influence_level: InfluenceLevel
    notes: str | None
    actor_type: ActorType
    system_description: str | None
    created_at: datetime
    updated_at: datetime
