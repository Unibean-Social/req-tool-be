import uuid
from datetime import date, datetime

from pydantic import BaseModel, model_validator

from app.models.sprint import SprintStatus
from app.schemas.requirements import StoryResponse


class SprintCreateRequest(BaseModel):
    name: str
    goal: str | None = None
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def end_after_start(self) -> "SprintCreateRequest":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class SprintUpdateRequest(BaseModel):
    name: str | None = None
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: SprintStatus | None = None


class SprintResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    goal: str | None
    start_date: date
    end_date: date
    status: SprintStatus
    github_milestone_number: int | None
    created_at: datetime
    updated_at: datetime


class SprintDetailResponse(SprintResponse):
    stories: list[StoryResponse] = []


class AssignStoriesRequest(BaseModel):
    story_ids: list[uuid.UUID]


class ReadinessIssue(BaseModel):
    story_id: uuid.UUID
    prefix: str
    title: str
    problems: list[str]


class SprintReadinessReport(BaseModel):
    ready: bool
    issues: list[ReadinessIssue]
