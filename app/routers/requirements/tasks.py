import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user
from app.models.requirements import TERMINAL_STATUSES, CloseReason, Epic, Feature, ItemStatus, ItemType, Story, Task
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
)
from app.schemas.response import ApiResponse

from ._helpers import _next_task_prefix, _require_project_access, _update_parent_references

router = APIRouter(prefix="/projects/{project_id}", tags=["tasks"])


@router.post("/tasks", response_model=ApiResponse[TaskResponse], status_code=status.HTTP_201_CREATED)
async def create_task(
    project_id: uuid.UUID,
    body: TaskCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id == body.story_id, Epic.project_id == project_id)
    )
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found")
    prefix = await _next_task_prefix(story, db)
    task = Task(
        story_id=story.id,
        prefix=prefix,
        title=body.title,
        description=body.description,
        priority=body.priority,
        labels=body.labels,
        assignee_id=body.assignee_id,
        category=body.category,
        estimated_hours=body.estimated_hours,
    )
    db.add(task)
    await db.flush()
    _update_parent_references(story, task.prefix, "add")
    return created(task)


@router.get("/tasks", response_model=ApiResponse[list[TaskResponse]])
async def list_tasks(
    project_id: uuid.UUID,
    story_id: uuid.UUID | None = Query(None),
    item_status: ItemStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    stmt = (
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id)
    )
    if story_id:
        stmt = stmt.where(Task.story_id == story_id)
    if item_status:
        stmt = stmt.where(Task.status == item_status)
    stmt = stmt.order_by(Task.prefix).limit(limit).offset(offset)
    return ok((await db.execute(stmt)).scalars().all())


@router.get("/tasks/{task_id}", response_model=ApiResponse[TaskResponse])
async def get_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Task.id == task_id, Epic.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return ok(task)


@router.patch("/tasks/{task_id}", response_model=ApiResponse[TaskResponse])
async def update_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Task.id == task_id, Epic.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    if body.title is not None:
        task.title = body.title
    if body.description is not None:
        task.description = body.description
    if body.status is not None:
        task.status = body.status
    if body.priority is not None:
        task.priority = body.priority
    if body.labels is not None:
        task.labels = body.labels
    if body.assignee_id is not None:
        task.assignee_id = body.assignee_id
    if body.category is not None:
        task.category = body.category
    if body.estimated_hours is not None:
        task.estimated_hours = body.estimated_hours
    return ok(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Task.id == task_id, Epic.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    story = await db.get(Story, task.story_id)
    if story:
        _update_parent_references(story, task.prefix, "remove")
    await db.delete(task)


@router.patch("/tasks/{task_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Task.id == task_id, Epic.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status in TERMINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Task is already closed")
    task.status = ItemStatus(body.reason.value)
    close = CloseReason(
        item_type=ItemType.task,
        item_id=task.id,
        reason=body.reason,
        comment=body.comment,
        closed_by=user.id,
    )
    db.add(close)
    await db.flush()
    return ok(close)
