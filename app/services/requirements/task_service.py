from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.requirements import (
    TERMINAL_STATUSES,
    CloseReason,
    Epic,
    Feature,
    ItemStatus,
    ItemType,
    Story,
    Task,
)
from app.models.user import User
from app.schemas.requirements import CloseRequest, TaskCreateRequest, TaskUpdateRequest
from app.services.requirements.helpers import _next_task_prefix, _update_parent_references


class TaskService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        result = await self.db.execute(
            select(Task)
            .join(Story, Task.story_id == Story.id)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Task.id == task_id, Epic.project_id == project_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
        return task

    async def create(self, project_id: uuid.UUID, body: TaskCreateRequest) -> Task:
        result = await self.db.execute(
            select(Story)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Story.id == body.story_id, Epic.project_id == project_id)
        )
        story = result.scalar_one_or_none()
        if not story:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found")
        prefix = await _next_task_prefix(story, self.db)
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
        self.db.add(task)
        await self.db.flush()
        _update_parent_references(story, task.prefix, "add")
        return task

    async def list(
        self,
        project_id: uuid.UUID,
        story_id: uuid.UUID | None = None,
        item_status: ItemStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
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
        return list((await self.db.execute(stmt)).scalars().all())

    async def get(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        return await self._get_task(project_id, task_id)

    async def update(
        self, project_id: uuid.UUID, task_id: uuid.UUID, body: TaskUpdateRequest
    ) -> Task:
        task = await self._get_task(project_id, task_id)
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
        return task

    async def delete(self, project_id: uuid.UUID, task_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(Task)
            .join(Story, Task.story_id == Story.id)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Task.id == task_id, Epic.project_id == project_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
        story = await self.db.get(Story, task.story_id)
        if story:
            _update_parent_references(story, task.prefix, "remove")
        await self.db.delete(task)

    async def close(
        self, project_id: uuid.UUID, task_id: uuid.UUID, body: CloseRequest, user: User
    ) -> CloseReason:
        task = await self._get_task(project_id, task_id)
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
        self.db.add(close)
        await self.db.flush()
        return close
