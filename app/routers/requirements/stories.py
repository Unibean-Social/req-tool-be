import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_github_service, get_story_service
from app.models.requirements import ItemStatus
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    StoryBuilderRequest,
    StoryResponse,
    StoryUpdateRequest,
)
from app.schemas.response import ApiResponse
from app.services.github_service import GithubService
from app.services.requirements.story_service import StoryService

router = APIRouter(prefix="/projects/{project_id}", tags=["stories"])


@router.get("/stories", response_model=ApiResponse[list[StoryResponse]])
async def list_stories(
    project_id: uuid.UUID,
    feature_id: uuid.UUID | None = Query(None),
    item_status: ItemStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    service: StoryService = Depends(get_story_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id, feature_id, item_status, limit, offset))


@router.get("/stories/{user_story_id}", response_model=ApiResponse[StoryResponse])
async def get_story(
    project_id: uuid.UUID,
    user_story_id: uuid.UUID,
    user: User = Depends(current_user),
    service: StoryService = Depends(get_story_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id, user_story_id))


@router.patch("/stories/{user_story_id}", response_model=ApiResponse[StoryResponse])
async def update_story(
    project_id: uuid.UUID,
    user_story_id: uuid.UUID,
    body: StoryUpdateRequest,
    user: User = Depends(current_user),
    service: StoryService = Depends(get_story_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, user_story_id, body))


@router.delete("/stories/{user_story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(
    project_id: uuid.UUID,
    user_story_id: uuid.UUID,
    user: User = Depends(current_user),
    service: StoryService = Depends(get_story_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, user_story_id)


@router.patch("/stories/{user_story_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_story(
    project_id: uuid.UUID,
    user_story_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    service: StoryService = Depends(get_story_service),
    github_service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.close(project_id, user_story_id, body, user, github_service=github_service))


@router.post("/story-builder", response_model=ApiResponse[StoryResponse], status_code=status.HTTP_201_CREATED)
async def story_builder(
    project_id: uuid.UUID,
    body: StoryBuilderRequest,
    user: User = Depends(current_user),
    service: StoryService = Depends(get_story_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.build(project_id, body))
