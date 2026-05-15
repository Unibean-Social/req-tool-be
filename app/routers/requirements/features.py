import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_feature_service
from app.models.requirements import ItemStatus
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    FeatureCreateRequest,
    FeatureResponse,
    FeatureUpdateRequest,
)
from app.schemas.response import ApiResponse
from app.services.requirements.feature_service import FeatureService

router = APIRouter(prefix="/projects/{project_id}", tags=["features"])


@router.post("/features", response_model=ApiResponse[FeatureResponse], status_code=status.HTTP_201_CREATED)
async def create_feature(
    project_id: uuid.UUID,
    body: FeatureCreateRequest,
    user: User = Depends(current_user),
    service: FeatureService = Depends(get_feature_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create(project_id, body))


@router.get("/features", response_model=ApiResponse[list[FeatureResponse]])
async def list_features(
    project_id: uuid.UUID,
    epic_id: uuid.UUID | None = Query(None),
    item_status: ItemStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    service: FeatureService = Depends(get_feature_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id, epic_id, item_status, limit, offset))


@router.get("/features/{feature_id}", response_model=ApiResponse[FeatureResponse])
async def get_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    user: User = Depends(current_user),
    service: FeatureService = Depends(get_feature_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id, feature_id))


@router.patch("/features/{feature_id}", response_model=ApiResponse[FeatureResponse])
async def update_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: FeatureUpdateRequest,
    user: User = Depends(current_user),
    service: FeatureService = Depends(get_feature_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, feature_id, body))


@router.delete("/features/{feature_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    user: User = Depends(current_user),
    service: FeatureService = Depends(get_feature_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, feature_id)


@router.patch("/features/{feature_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    service: FeatureService = Depends(get_feature_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.close(project_id, feature_id, body, user))
