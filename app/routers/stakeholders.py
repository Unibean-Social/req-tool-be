import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.guards import require_project_access
from app.models.stakeholder import ActorType
from app.core.responses import created, ok
from app.deps import current_user, get_stakeholder_service
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.stakeholder import StakeholderCreateRequest, StakeholderResponse, StakeholderUpdateRequest
from app.services.stakeholder_service import StakeholderService

router = APIRouter(prefix="/projects/{project_id}/stakeholders", tags=["Stakeholders"])


@router.post("", response_model=ApiResponse[StakeholderResponse], status_code=status.HTTP_201_CREATED)
async def create_stakeholder(
    project_id: uuid.UUID,
    body: StakeholderCreateRequest,
    user: User = Depends(current_user),
    service: StakeholderService = Depends(get_stakeholder_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create(project_id, body))


@router.get("", response_model=ApiResponse[list[StakeholderResponse]])
async def list_stakeholders(
    project_id: uuid.UUID,
    actor_type: list[ActorType] | None = Query(default=None),
    user: User = Depends(current_user),
    service: StakeholderService = Depends(get_stakeholder_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id, actor_types=actor_type))


@router.get("/{stakeholder_id}", response_model=ApiResponse[StakeholderResponse])
async def get_stakeholder(
    project_id: uuid.UUID,
    stakeholder_id: uuid.UUID,
    user: User = Depends(current_user),
    service: StakeholderService = Depends(get_stakeholder_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id, stakeholder_id))


@router.patch("/{stakeholder_id}", response_model=ApiResponse[StakeholderResponse])
async def update_stakeholder(
    project_id: uuid.UUID,
    stakeholder_id: uuid.UUID,
    body: StakeholderUpdateRequest,
    user: User = Depends(current_user),
    service: StakeholderService = Depends(get_stakeholder_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, stakeholder_id, body))


@router.delete("/{stakeholder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stakeholder(
    project_id: uuid.UUID,
    stakeholder_id: uuid.UUID,
    user: User = Depends(current_user),
    service: StakeholderService = Depends(get_stakeholder_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, stakeholder_id)
