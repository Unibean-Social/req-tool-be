import uuid
from datetime import datetime
from pydantic import BaseModel


class ActorCreateRequest(BaseModel):
    name: str
    role_description: str | None = None


class ActorUpdateRequest(BaseModel):
    name: str | None = None
    role_description: str | None = None


class ActorResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    role_description: str | None
    created_at: datetime
