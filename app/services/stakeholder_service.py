from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stakeholder import ActorType, Stakeholder
from app.schemas.stakeholder import StakeholderCreateRequest, StakeholderResponse, StakeholderUpdateRequest


class StakeholderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get(self, project_id: uuid.UUID, stakeholder_id: uuid.UUID) -> Stakeholder:
        result = await self.db.execute(
            select(Stakeholder).where(
                Stakeholder.id == stakeholder_id,
                Stakeholder.project_id == project_id,
            )
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy stakeholder")
        return obj

    async def create(self, project_id: uuid.UUID, body: StakeholderCreateRequest) -> StakeholderResponse:
        obj = Stakeholder(
            project_id=project_id,
            **body.model_dump(),
        )
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return StakeholderResponse.model_validate(obj)

    async def list(
        self, project_id: uuid.UUID, actor_types: list[ActorType] | None = None
    ) -> list[StakeholderResponse]:
        q = select(Stakeholder).where(Stakeholder.project_id == project_id)
        if actor_types:
            q = q.where(Stakeholder.actor_type.in_(actor_types))
        result = await self.db.execute(q.order_by(Stakeholder.created_at))
        return [StakeholderResponse.model_validate(s) for s in result.scalars().all()]

    async def get(self, project_id: uuid.UUID, stakeholder_id: uuid.UUID) -> StakeholderResponse:
        return StakeholderResponse.model_validate(await self._get(project_id, stakeholder_id))

    async def update(
        self, project_id: uuid.UUID, stakeholder_id: uuid.UUID, body: StakeholderUpdateRequest
    ) -> StakeholderResponse:
        obj = await self._get(project_id, stakeholder_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        await self.db.flush()
        await self.db.refresh(obj)
        return StakeholderResponse.model_validate(obj)

    async def delete(self, project_id: uuid.UUID, stakeholder_id: uuid.UUID) -> None:
        obj = await self._get(project_id, stakeholder_id)
        await self.db.delete(obj)
