from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stakeholder import Stakeholder
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
            name=body.name,
            role=body.role,
            impact_area=body.impact_area,
            influence_level=body.influence_level,
            notes=body.notes,
        )
        self.db.add(obj)
        await self.db.flush()
        return StakeholderResponse.model_validate(obj)

    async def list(self, project_id: uuid.UUID) -> list[StakeholderResponse]:
        result = await self.db.execute(
            select(Stakeholder)
            .where(Stakeholder.project_id == project_id)
            .order_by(Stakeholder.created_at)
        )
        return [StakeholderResponse.model_validate(s) for s in result.scalars().all()]

    async def get(self, project_id: uuid.UUID, stakeholder_id: uuid.UUID) -> StakeholderResponse:
        return StakeholderResponse.model_validate(await self._get(project_id, stakeholder_id))

    async def update(
        self, project_id: uuid.UUID, stakeholder_id: uuid.UUID, body: StakeholderUpdateRequest
    ) -> StakeholderResponse:
        obj = await self._get(project_id, stakeholder_id)
        if body.name is not None:
            obj.name = body.name
        if body.role is not None:
            obj.role = body.role
        if body.impact_area is not None:
            obj.impact_area = body.impact_area
        if body.influence_level is not None:
            obj.influence_level = body.influence_level
        if body.notes is not None:
            obj.notes = body.notes
        return StakeholderResponse.model_validate(obj)

    async def delete(self, project_id: uuid.UUID, stakeholder_id: uuid.UUID) -> None:
        obj = await self._get(project_id, stakeholder_id)
        await self.db.delete(obj)
