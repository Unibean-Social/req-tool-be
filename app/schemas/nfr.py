import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.nfr import NFRCategory
from app.models.requirements import Priority


class NFRCreateRequest(BaseModel):
    category: NFRCategory
    description: str
    priority: Priority = Priority.medium
    feature_ids: list[uuid.UUID] = []


class NFRUpdateRequest(BaseModel):
    category: NFRCategory | None = None
    description: str | None = None
    priority: Priority | None = None
    feature_ids: list[uuid.UUID] | None = None


class NFRResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    category: NFRCategory
    description: str
    priority: Priority
    feature_ids: list[uuid.UUID] = []
    created_at: datetime
    updated_at: datetime
