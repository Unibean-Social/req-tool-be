import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_epic_service, get_feature_service, get_github_service
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    EpicResponse,
    EpicTree,
    EpicUpdateRequest,
    FeatureCreateRequest,
    FeatureResponse,
)
from app.schemas.response import ApiResponse
from app.services.github_service import GithubService
from app.services.requirements.epic_service import EpicService
from app.services.requirements.feature_service import FeatureService

router = APIRouter(prefix="/projects/{project_id}", tags=["Epics"])


@router.get("/epics", response_model=ApiResponse[list[EpicResponse]])
async def list_epics(
    project_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id, limit=limit, offset=offset))


@router.get("/epics/{epic_id}", response_model=ApiResponse[EpicResponse])
async def get_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id, epic_id))


@router.patch("/epics/{epic_id}", response_model=ApiResponse[EpicResponse])
async def update_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    body: EpicUpdateRequest,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, epic_id, body))


@router.delete("/epics/{epic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, epic_id)


@router.patch("/epics/{epic_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
    github_service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.close(project_id, epic_id, body, user, github_service=github_service))


@router.get("/requirements/tree", response_model=ApiResponse[list[EpicTree]])
async def get_requirements_tree(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_tree(project_id))


@router.post(
    "/epics/{epic_id}/features",
    response_model=ApiResponse[FeatureResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_feature_for_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    body: FeatureCreateRequest,
    user: User = Depends(current_user),
    feature_service: FeatureService = Depends(get_feature_service),
):
    await require_project_access(project_id, user, feature_service.db)
    return created(await feature_service.create(project_id, epic_id, body))
