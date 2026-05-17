from __future__ import annotations

from pydantic import BaseModel

from app.schemas.actor import ActorResponse
from app.schemas.requirements import EpicResponse, FeatureResponse, StoryResponse


class RequirementModelResponse(BaseModel):
    model_config = {"from_attributes": True}

    actor: ActorResponse
    epics: list[EpicResponse]
    features: list[FeatureResponse]
    user_stories: list[StoryResponse]
