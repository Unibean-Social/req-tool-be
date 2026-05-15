import uuid

from fastapi import APIRouter, Depends, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_actor_service
from app.models.user import User
from app.schemas.actor import ActorCreateRequest, ActorResponse, ActorUpdateRequest
from app.schemas.response import ApiResponse
from app.services.actor_service import ActorService

router = APIRouter(prefix="/projects/{project_id}/actors", tags=["actors"])


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
