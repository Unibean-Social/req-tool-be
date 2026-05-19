import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, computed_field, field_validator, model_validator

from app.models.project_business import RuleType


def _normalize_action_description(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("description không được để trống")
    words = value.split()
    if len(words) < 2:
        raise ValueError("description phải có ít nhất 2 từ theo mẫu '{Actor} {hành động}'")
    # Capitalize first character (handles ASCII and Unicode/Vietnamese)
    value = value[0].upper() + value[1:]
    # Ensure ends with sentence-ending punctuation
    if value[-1] not in ".!?":
        value += "."
    return value


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


# ── Rules ─────────────────────────────────────────────────────────────────────

class ProjectRuleCreate(BaseModel):
    rule_def: str
    type: RuleType
    is_dynamic: bool = False
    source: str | None = None


class ProjectRuleUpdate(BaseModel):
    rule_def: str | None = None
    type: RuleType | None = None
    is_dynamic: bool | None = None
    source: str | None = None


class ProjectRuleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    rule_def: str
    type: RuleType
    is_dynamic: bool
    source: str | None
    created_at: datetime
    updated_at: datetime


# ── Flow Actions ───────────────────────────────────────────────────────────────

class ProjectFlowActionCreate(BaseModel):
    order: int = 0
    description: str
    actor_id: uuid.UUID | None = None

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: str) -> str:
        return _normalize_action_description(v)


class ProjectFlowActionUpdate(BaseModel):
    order: int | None = None
    description: str | None = None
    actor_id: uuid.UUID | None = None

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: str | None) -> str | None:
        return _normalize_action_description(v) if v is not None else v


class ProjectFlowActionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    flow_id: uuid.UUID
    actor_id: uuid.UUID | None
    order: int
    description: str
    rules: list[ProjectRuleResponse] = []
    created_at: datetime
    updated_at: datetime


# ── Swimlane schemas ───────────────────────────────────────────────────────────

class SwimlaneLane(BaseModel):
    id: str
    title: str


class SwimlaneNode(BaseModel):
    id: str
    lane_id: str
    y: float


class SwimlaneAction(BaseModel):
    id: uuid.UUID  # must reference an existing ProjectFlowAction.id
    lane_id: str
    notation: Literal["action", "objectNode", "decision", "merge", "fork", "join"] = "action"
    index: int | None = None
    y: float


class SwimlaneFlow(BaseModel):
    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None
    label: str | None = None
    flow_type: Literal["control", "object"] = "control"
    label_offset: dict | None = None


class SwimlaneRequest(BaseModel):
    title: str
    lanes: list[SwimlaneLane]
    initial_node: SwimlaneNode
    activity_final_node: SwimlaneNode
    actions: list[SwimlaneAction] = []
    flows: list[SwimlaneFlow] = []
    layout: dict | None = None

    @model_validator(mode="after")
    def check_referential_integrity(self) -> "SwimlaneRequest":
        lane_ids = {lane.id for lane in self.lanes}
        for special in (self.initial_node, self.activity_final_node):
            if special.lane_id not in lane_ids:
                raise ValueError(
                    f"node '{special.id}' has lane_id '{special.lane_id}' not in lanes"
                )
        for action in self.actions:
            if action.lane_id not in lane_ids:
                raise ValueError(
                    f"action '{action.id}' has lane_id '{action.lane_id}' not in lanes"
                )
        node_ids = (
            {self.initial_node.id, self.activity_final_node.id}
            | {str(a.id) for a in self.actions}
        )
        for flow in self.flows:
            if flow.source not in node_ids:
                raise ValueError(f"flow '{flow.id}' source '{flow.source}' is not a known node id")
            if flow.target not in node_ids:
                raise ValueError(f"flow '{flow.id}' target '{flow.target}' is not a known node id")
        return self


# ── Flows ──────────────────────────────────────────────────────────────────────

class ProjectFlowCreate(BaseModel):
    code: str
    name: str
    description: str | None = None
    actions: list["ProjectFlowActionCreate"] = []


class ProjectFlowUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None


class ProjectFlowResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    description: str | None
    actions: list[ProjectFlowActionResponse] = []
    created_at: datetime
    updated_at: datetime

    # FE compatibility — FE still uses title/order field names
    @computed_field
    @property
    def title(self) -> str:
        return self.name

    order: int = 0


class ProjectFlowDetailResponse(ProjectFlowResponse):
    swimlane: dict | None = None
