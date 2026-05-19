import uuid

from fastapi import APIRouter, Depends, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_nfr_service
from app.models.nfr import NFRCategory
from app.models.requirements import Priority
from app.models.user import User
from app.schemas.nfr import NFRCreateRequest, NFRResponse, NFRUpdateRequest
from app.schemas.response import ApiResponse
from app.services.nfr_service import NFRService

router = APIRouter(prefix="/projects/{project_id}/nfrs", tags=["user-requirements"])


@router.post("", response_model=ApiResponse[NFRResponse], status_code=status.HTTP_201_CREATED)
async def create_nfr(
    project_id: uuid.UUID,
    body: NFRCreateRequest,
    user: User = Depends(current_user),
    service: NFRService = Depends(get_nfr_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create(project_id, body))


@router.get("", response_model=ApiResponse[list[NFRResponse]])
async def list_nfrs(
    project_id: uuid.UUID,
    category: NFRCategory | None = None,
    priority: Priority | None = None,
    user: User = Depends(current_user),
    service: NFRService = Depends(get_nfr_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id, category=category, priority=priority))


@router.get("/{nfr_id}", response_model=ApiResponse[NFRResponse])
async def get_nfr(
    project_id: uuid.UUID,
    nfr_id: uuid.UUID,
    user: User = Depends(current_user),
    service: NFRService = Depends(get_nfr_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id, nfr_id))


@router.patch("/{nfr_id}", response_model=ApiResponse[NFRResponse])
async def update_nfr(
    project_id: uuid.UUID,
    nfr_id: uuid.UUID,
    body: NFRUpdateRequest,
    user: User = Depends(current_user),
    service: NFRService = Depends(get_nfr_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, nfr_id, body))


@router.delete("/{nfr_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nfr(
    project_id: uuid.UUID,
    nfr_id: uuid.UUID,
    user: User = Depends(current_user),
    service: NFRService = Depends(get_nfr_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, nfr_id)


@router.post("/{nfr_id}/features/{feature_id}", response_model=ApiResponse[NFRResponse])
async def add_feature_link(
    project_id: uuid.UUID,
    nfr_id: uuid.UUID,
    feature_id: uuid.UUID,
    user: User = Depends(current_user),
    service: NFRService = Depends(get_nfr_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.add_feature_link(project_id, nfr_id, feature_id))


@router.delete("/{nfr_id}/features/{feature_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_feature_link(
    project_id: uuid.UUID,
    nfr_id: uuid.UUID,
    feature_id: uuid.UUID,
    user: User = Depends(current_user),
    service: NFRService = Depends(get_nfr_service),
):
    await require_project_access(project_id, user, service.db)
    await service.remove_feature_link(project_id, nfr_id, feature_id)
