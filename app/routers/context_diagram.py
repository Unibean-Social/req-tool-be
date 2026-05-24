import uuid

from fastapi import APIRouter, Depends, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_context_diagram_service
from app.models.user import User
from app.schemas.context_diagram import (
    ContextDiagramFlow,
    ContextDiagramResponse,
    FlowCreateRequest,
    FlowUpdateRequest,
    LayoutSaveRequest,
    SyncResult,
)
from app.schemas.response import ApiResponse
from app.services.context_diagram_service import ContextDiagramService

router = APIRouter(
    prefix="/projects/{project_id}/context-diagram",
    tags=["Context Diagram"],
)


@router.get("", response_model=ApiResponse[ContextDiagramResponse])
async def get_context_diagram(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ContextDiagramService = Depends(get_context_diagram_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id))


@router.put("/layout", response_model=ApiResponse[None])
async def save_layout(
    project_id: uuid.UUID,
    body: LayoutSaveRequest,
    user: User = Depends(current_user),
    service: ContextDiagramService = Depends(get_context_diagram_service),
):
    await require_project_access(project_id, user, service.db)
    await service.save_layout(project_id, body)
    return ok(None, "Layout saved.")


@router.post("/flows", response_model=ApiResponse[ContextDiagramFlow], status_code=status.HTTP_201_CREATED)
async def create_flow(
    project_id: uuid.UUID,
    body: FlowCreateRequest,
    user: User = Depends(current_user),
    service: ContextDiagramService = Depends(get_context_diagram_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_flow(project_id, body))


@router.patch("/flows/{flow_id}", response_model=ApiResponse[ContextDiagramFlow])
async def update_flow(
    project_id: uuid.UUID,
    flow_id: str,
    body: FlowUpdateRequest,
    user: User = Depends(current_user),
    service: ContextDiagramService = Depends(get_context_diagram_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_flow(project_id, flow_id, body))


@router.delete("/flows/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(
    project_id: uuid.UUID,
    flow_id: str,
    user: User = Depends(current_user),
    service: ContextDiagramService = Depends(get_context_diagram_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_flow(project_id, flow_id)


@router.post("/sync", response_model=ApiResponse[SyncResult])
async def sync_from_flows(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ContextDiagramService = Depends(get_context_diagram_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.sync(project_id))
