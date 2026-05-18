import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_github_service, get_task_service
from app.models.requirements import ItemStatus
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
)
from app.schemas.response import ApiResponse
from app.services.github_service import GithubService
from app.services.requirements.task_service import TaskService

router = APIRouter(prefix="/projects/{project_id}", tags=["tasks"])


@router.post("/tasks", response_model=ApiResponse[TaskResponse], status_code=status.HTTP_201_CREATED)
async def create_task(
    project_id: uuid.UUID,
    body: TaskCreateRequest,
    user: User = Depends(current_user),
    service: TaskService = Depends(get_task_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create(project_id, body))


@router.get("/tasks", response_model=ApiResponse[list[TaskResponse]])
async def list_tasks(
    project_id: uuid.UUID,
    story_id: uuid.UUID | None = Query(None),
    item_status: ItemStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    service: TaskService = Depends(get_task_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id, story_id, item_status, limit, offset))


@router.get("/tasks/{task_id}", response_model=ApiResponse[TaskResponse])
async def get_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(current_user),
    service: TaskService = Depends(get_task_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id, task_id))


@router.patch("/tasks/{task_id}", response_model=ApiResponse[TaskResponse])
async def update_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskUpdateRequest,
    user: User = Depends(current_user),
    service: TaskService = Depends(get_task_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, task_id, body))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(current_user),
    service: TaskService = Depends(get_task_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, task_id)


@router.patch("/tasks/{task_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    service: TaskService = Depends(get_task_service),
    github_service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.close(project_id, task_id, body, user, github_service=github_service))
