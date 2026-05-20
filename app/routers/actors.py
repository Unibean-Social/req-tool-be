import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_actor_service, get_epic_service
from app.models.user import User
from app.schemas.actor import ActorCreateRequest, ActorResponse, ActorUpdateRequest
from app.schemas.requirement_model import RequirementModelResponse
from app.schemas.requirements import CanvasLayoutRequest, CanvasLayoutResponse, EpicCreateRequest, EpicResponse
from app.schemas.response import ApiResponse
from app.services.actor_service import ActorService
from app.services.requirements.epic_service import EpicService

router = APIRouter(prefix="/projects/{project_id}/actors", tags=["Actors"])


@router.post("", response_model=ApiResponse[ActorResponse], status_code=status.HTTP_201_CREATED)
async def create_actor(
    project_id: uuid.UUID,
    body: ActorCreateRequest,
    user: User = Depends(current_user),
    service: ActorService = Depends(get_actor_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create(project_id, body))


@router.get("", response_model=ApiResponse[list[ActorResponse]])
async def list_actors(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ActorService = Depends(get_actor_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id))


@router.get("/{actor_id}", response_model=ApiResponse[ActorResponse])
async def get_actor(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ActorService = Depends(get_actor_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id, actor_id))


@router.post(
    "/{actor_id}/epics",
    response_model=ApiResponse[EpicResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_epic_for_actor(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: EpicCreateRequest,
    user: User = Depends(current_user),
    actor_service: ActorService = Depends(get_actor_service),
    epic_service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, actor_service.db)
    await actor_service.get(project_id, actor_id)  # 404 if actor doesn't belong to this project
    return created(await epic_service.create(project_id, body, user, actor_id=actor_id))


@router.get(
    "/{actor_id}/requirement-model",
    response_model=ApiResponse[RequirementModelResponse],
)
async def get_requirement_model(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    user: User = Depends(current_user),
    epic_service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, epic_service.db)
    return ok(await epic_service.get_requirement_model(project_id, actor_id))


@router.get(
    "/{actor_id}/canvas-layout",
    response_model=ApiResponse[CanvasLayoutResponse],
)
async def get_canvas_layout(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ActorService = Depends(get_actor_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_canvas_layout(project_id, actor_id))


@router.put(
    "/{actor_id}/canvas-layout",
    response_model=ApiResponse[CanvasLayoutResponse],
)
async def put_canvas_layout(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: CanvasLayoutRequest,
    user: User = Depends(current_user),
    service: ActorService = Depends(get_actor_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.put_canvas_layout(project_id, actor_id, body))


@router.patch("/{actor_id}", response_model=ApiResponse[ActorResponse])
async def update_actor(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: ActorUpdateRequest,
    user: User = Depends(current_user),
    service: ActorService = Depends(get_actor_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, actor_id, body))


@router.delete("/{actor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_actor(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ActorService = Depends(get_actor_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, actor_id)
