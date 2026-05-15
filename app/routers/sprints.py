import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_sprint_service
from app.models.sprint import SprintStatus
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.sprint import (
    AssignStoriesRequest,
    SprintCreateRequest,
    SprintDetailResponse,
    SprintReadinessReport,
    SprintResponse,
    SprintUpdateRequest,
)
from app.services.sprint_service import SprintService

router = APIRouter(prefix="/projects/{project_id}/sprints", tags=["sprints"])


@router.post("", response_model=ApiResponse[SprintResponse], status_code=status.HTTP_201_CREATED)
async def create_sprint(
    project_id: uuid.UUID,
    body: SprintCreateRequest,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create(project_id, body))


@router.get("", response_model=ApiResponse[list[SprintResponse]])
async def list_sprints(
    project_id: uuid.UUID,
    status: SprintStatus | None = Query(None),
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id, status))


@router.get("/{sprint_id}", response_model=ApiResponse[SprintDetailResponse])
async def get_sprint(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_detail(project_id, sprint_id))


@router.patch("/{sprint_id}", response_model=ApiResponse[SprintResponse])
async def update_sprint(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    body: SprintUpdateRequest,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, sprint_id, body))


@router.delete("/{sprint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sprint(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, sprint_id)


@router.post("/{sprint_id}/stories", response_model=ApiResponse[SprintResponse])
async def assign_stories(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    body: AssignStoriesRequest,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.assign_stories(project_id, sprint_id, body))


@router.delete("/{sprint_id}/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_story_from_sprint(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    story_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    await service.remove_story(project_id, sprint_id, story_id)


@router.get("/{sprint_id}/readiness", response_model=ApiResponse[SprintReadinessReport])
async def sprint_readiness(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.readiness(project_id, sprint_id))


@router.post("/{sprint_id}/push-milestone", response_model=ApiResponse[SprintResponse])
async def push_milestone(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.push_milestone(project_id, sprint_id))


@router.post("/{sprint_id}/close-milestone", response_model=ApiResponse[SprintResponse])
async def close_milestone(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SprintService = Depends(get_sprint_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.close_milestone(project_id, sprint_id))
