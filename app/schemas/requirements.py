import uuid
from datetime import datetime
from typing import Any

from typing import Literal

from pydantic import BaseModel, field_validator

TaskCategory = Literal["api", "database", "ui", "auth", "testing", "devops", "documentation"]

from app.models.requirements import CloseReasonEnum, ItemStatus, Priority


class AcceptanceCriteriaIn(BaseModel):
    description: str
    order: int = 0


class AcceptanceCriteriaResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    description: str
    order: int
    done: bool = False


# ── Epic ──────────────────────────────────────────────────────────────────────


class EpicCreateRequest(BaseModel):
    title: str
    description: str | None = None
    priority: Priority = Priority.medium
    labels: list[str] = []


class EpicUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: ItemStatus | None = None
    priority: Priority | None = None
    labels: list[str] | None = None

    @field_validator("status")
    @classmethod
    def no_direct_terminal(cls, v: ItemStatus | None) -> ItemStatus | None:
        from app.models.requirements import TERMINAL_STATUSES
        if v in TERMINAL_STATUSES:
            raise ValueError("Sử dụng endpoint /close để đặt trạng thái kết thúc")
        return v


class EpicResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    prefix: str
    title: str
    description: str | None
    status: ItemStatus
    priority: Priority
    labels: Any
    references: Any = None
    total_story_points: int = 0
    total_business_value: int = 0
    feature_count: int = 0
    story_count: int = 0
    created_at: datetime
    updated_at: datetime


# ── Feature ───────────────────────────────────────────────────────────────────


class FeatureCreateRequest(BaseModel):
    title: str
    description: str | None = None
    priority: Priority = Priority.medium
    labels: list[str] = []


class FeatureUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: ItemStatus | None = None
    priority: Priority | None = None
    labels: list[str] | None = None

    @field_validator("status")
    @classmethod
    def no_direct_terminal(cls, v: ItemStatus | None) -> ItemStatus | None:
        from app.models.requirements import TERMINAL_STATUSES
        if v in TERMINAL_STATUSES:
            raise ValueError("Sử dụng endpoint /close để đặt trạng thái kết thúc")
        return v


class FeatureResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    epic_id: uuid.UUID
    prefix: str
    title: str
    description: str | None
    status: ItemStatus
    priority: Priority
    labels: Any
    references: Any = None
    warnings: list[str] = []
    total_story_points: int = 0
    total_business_value: int = 0
    story_count: int = 0
    created_at: datetime
    updated_at: datetime


# ── Story ─────────────────────────────────────────────────────────────────────


class StoryCreateRequest(BaseModel):
    title: str
    description: str | None = None
    actor_ref: str | None = None
    action_text: str | None = None
    goal_text: str | None = None
    priority: Priority = Priority.medium
    labels: list[str] = []
    story_points: int | None = None
    business_value: int | None = None


class StoryUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    actor_ref: str | None = None
    action_text: str | None = None
    goal_text: str | None = None
    status: ItemStatus | None = None
    priority: Priority | None = None
    labels: list[str] | None = None
    story_points: int | None = None
    business_value: int | None = None
    acceptance_criteria: list[AcceptanceCriteriaIn] | None = None

    @field_validator("status")
    @classmethod
    def no_direct_terminal(cls, v: ItemStatus | None) -> ItemStatus | None:
        from app.models.requirements import TERMINAL_STATUSES
        if v in TERMINAL_STATUSES:
            raise ValueError("Sử dụng endpoint /close để đặt trạng thái kết thúc")
        return v


class StoryBuilderRequest(BaseModel):
    feature_id: uuid.UUID
    actor_ref: str
    action_text: str
    goal_text: str
    priority: Priority = Priority.medium
    labels: list[str] = []
    acceptance_criteria: list[AcceptanceCriteriaIn]

    @field_validator("acceptance_criteria")
    @classmethod
    def require_at_least_one_ac(cls, v: list) -> list:
        if not v:
            raise ValueError("Phải có ít nhất một tiêu chí chấp nhận")
        return v

class StoryResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    feature_id: uuid.UUID
    prefix: str
    title: str
    description: str | None
    actor_ref: str | None
    action_text: str | None
    goal_text: str | None
    status: ItemStatus
    priority: Priority
    labels: Any
    references: Any = None
    story_points: int | None = None
    business_value: int | None = None
    acceptance_criteria: list[AcceptanceCriteriaResponse] = []
    created_at: datetime
    updated_at: datetime


# ── Task ──────────────────────────────────────────────────────────────────────


class TaskCreateRequest(BaseModel):
    story_id: uuid.UUID
    title: str
    description: str | None = None
    priority: Priority = Priority.medium
    labels: list[str] = []
    assignee_id: uuid.UUID | None = None
    category: TaskCategory | None = None
    estimated_hours: float | None = None


class TaskUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: ItemStatus | None = None
    priority: Priority | None = None
    labels: list[str] | None = None
    assignee_id: uuid.UUID | None = None
    category: TaskCategory | None = None
    estimated_hours: float | None = None

    @field_validator("status")
    @classmethod
    def no_direct_terminal(cls, v: ItemStatus | None) -> ItemStatus | None:
        from app.models.requirements import TERMINAL_STATUSES
        if v in TERMINAL_STATUSES:
            raise ValueError("Sử dụng endpoint /close để đặt trạng thái kết thúc")
        return v


class TaskResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    story_id: uuid.UUID
    prefix: str
    title: str
    description: str | None
    status: ItemStatus
    priority: Priority
    labels: Any
    references: Any = None
    assignee_id: uuid.UUID | None = None
    category: str | None = None
    estimated_hours: float | None = None
    created_at: datetime
    updated_at: datetime


# ── Close ─────────────────────────────────────────────────────────────────────


class CloseRequest(BaseModel):
    reason: CloseReasonEnum
    comment: str

    @field_validator("comment")
    @classmethod
    def comment_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nhận xét không được để trống")
        return v


class CloseReasonResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    item_type: str
    item_id: uuid.UUID
    reason: CloseReasonEnum
    comment: str
    closed_by: uuid.UUID
    created_at: datetime


# ── Hierarchy Tree ────────────────────────────────────────────────────────────


class TaskTree(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    prefix: str
    title: str
    status: ItemStatus
    priority: Priority


class StoryTree(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    prefix: str
    title: str
    status: ItemStatus
    priority: Priority
    tasks: list[TaskTree] = []


class FeatureTree(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    prefix: str
    title: str
    status: ItemStatus
    priority: Priority
    stories: list[StoryTree] = []


class EpicTree(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    prefix: str
    title: str
    status: ItemStatus
    priority: Priority
    features: list[FeatureTree] = []


# ── Requirement Model (aggregated tree) ───────────────────────────────────────


class CanvasLayoutNode(BaseModel):
    id: uuid.UUID
    kind: str
    x: float
    y: float
    collapsed: bool = False


class CanvasLayoutRequest(BaseModel):
    nodes: list[CanvasLayoutNode] = []


class CanvasLayoutResponse(BaseModel):
    nodes: list[CanvasLayoutNode] = []
