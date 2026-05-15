import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.schemas.requirements import CloseRequest, EpicCreateRequest, EpicUpdateRequest
from app.services.requirements.helpers import _bp12_check, _next_epic_prefix


class EpicService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, project_id: uuid.UUID, body: EpicCreateRequest, user: User) -> Epic:
        await _bp12_check(project_id, body.title, self.db)
        prefix = await _next_epic_prefix(project_id, self.db)
        epic = Epic(
            project_id=project_id,
            prefix=prefix,
            title=body.title,
            description=body.description,
            priority=body.priority,
            labels=body.labels,
        )
        self.db.add(epic)
        await self.db.flush()
        return epic

    async def list(self, project_id: uuid.UUID) -> list[Epic]:
        result = await self.db.execute(
            select(Epic).where(Epic.project_id == project_id).order_by(Epic.prefix)
        )
        return list(result.scalars().all())

    async def get(self, project_id: uuid.UUID, epic_id: uuid.UUID) -> Epic:
        result = await self.db.execute(
            select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id)
        )
        epic = result.scalar_one_or_none()
        if not epic:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Epic not found")
        return epic

    async def update(self, project_id: uuid.UUID, epic_id: uuid.UUID, body: EpicUpdateRequest) -> Epic:
        epic = await self.get(project_id, epic_id)
        if body.title is not None:
            await _bp12_check(project_id, body.title, self.db)
            epic.title = body.title
        if body.description is not None:
            epic.description = body.description
        if body.status is not None:
            epic.status = body.status
        if body.priority is not None:
            epic.priority = body.priority
        if body.labels is not None:
            epic.labels = body.labels
        return epic

    async def delete(self, project_id: uuid.UUID, epic_id: uuid.UUID) -> None:
        epic = await self.get(project_id, epic_id)
        await self.db.delete(epic)

    async def close(
        self, project_id: uuid.UUID, epic_id: uuid.UUID, body: CloseRequest, user: User
    ) -> CloseReason:
        epic = await self.get(project_id, epic_id)
        if epic.status in TERMINAL_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Epic is already closed")
        epic.status = ItemStatus(body.reason.value)
        close = CloseReason(
            item_type=ItemType.epic,
            item_id=epic.id,
            reason=body.reason,
            comment=body.comment,
            closed_by=user.id,
        )
        self.db.add(close)
        await self.db.flush()
        return close

    async def get_tree(self, project_id: uuid.UUID) -> list[Epic]:
        result = await self.db.execute(
            select(Epic)
            .where(Epic.project_id == project_id)
            .options(
                selectinload(Epic.features).selectinload(Feature.stories).selectinload(Story.tasks)
            )
            .order_by(Epic.prefix)
        )
        return list(result.scalars().all())
