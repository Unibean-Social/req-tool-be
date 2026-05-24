from pydantic import BaseModel, ConfigDict, field_validator


class ContextDiagramStakeholder(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    role: str | None = None


class ContextDiagramFlow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    target: str
    label: str = ""


class LayoutNode(BaseModel):
    id: str
    position: dict


class LayoutEdge(BaseModel):
    id: str
    waypoint: dict | None = None
    source_anchor: dict | None = None
    target_anchor: dict | None = None
    label_offset: dict | None = None


class ContextDiagramLayout(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nodes: list[LayoutNode]
    edges: list[LayoutEdge]


class ContextDiagramResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    center_label: str
    stakeholders: list[ContextDiagramStakeholder]
    flows: list[ContextDiagramFlow]
    layout: ContextDiagramLayout | None = None


class LayoutSaveRequest(BaseModel):
    nodes: list[LayoutNode]
    edges: list[LayoutEdge]


class FlowCreateRequest(BaseModel):
    source: str
    target: str
    label: str = ""

    @field_validator("target")
    @classmethod
    def one_endpoint_must_be_center(cls, target: str, info) -> str:
        source = info.data.get("source", "")
        if source != "center" and target != "center":
            raise ValueError("Một trong source hoặc target phải là 'center'")
        return target


class FlowUpdateRequest(BaseModel):
    label: str


class SyncResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    added_stakeholders: int
    added_flows: int
    diagram: ContextDiagramResponse
