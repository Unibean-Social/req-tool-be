import uuid
from datetime import datetime

from pydantic import BaseModel


class EstimateItemResponse(BaseModel):
    id: uuid.UUID
    voter_id: uuid.UUID
    value: str
    created_at: datetime
    updated_at: datetime


class EstimateListResponse(BaseModel):
    estimates: list[EstimateItemResponse]
    average: float | None
    story_points: int | None
