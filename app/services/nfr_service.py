from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nfr import NFR, NFRCategory
from app.models.requirements import Priority
from app.schemas.nfr import NFRCreateRequest, NFRResponse, NFRUpdateRequest


class NFRService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get(self, project_id: uuid.UUID, nfr_id: uuid.UUID) -> NFR:
        result = await self.db.execute(
            select(NFR).where(NFR.id == nfr_id, NFR.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy NFR")
        return obj

    async def create(self, project_id: uuid.UUID, body: NFRCreateRequest) -> NFRResponse:
        obj = NFR(
            project_id=project_id,
            category=body.category,
            description=body.description,
            priority=body.priority,
            source_feature_id=body.source_feature_id,
        )
        self.db.add(obj)
        await self.db.flush()
        return NFRResponse.model_validate(obj)

    async def list(
        self,
        project_id: uuid.UUID,
        category: NFRCategory | None = None,
        priority: Priority | None = None,
    ) -> list[NFRResponse]:
        stmt = select(NFR).where(NFR.project_id == project_id)
        if category is not None:
            stmt = stmt.where(NFR.category == category)
        if priority is not None:
            stmt = stmt.where(NFR.priority == priority)
        stmt = stmt.order_by(NFR.created_at)
        result = await self.db.execute(stmt)
        return [NFRResponse.model_validate(n) for n in result.scalars().all()]

    async def get(self, project_id: uuid.UUID, nfr_id: uuid.UUID) -> NFRResponse:
        return NFRResponse.model_validate(await self._get(project_id, nfr_id))

    async def update(
        self, project_id: uuid.UUID, nfr_id: uuid.UUID, body: NFRUpdateRequest
    ) -> NFRResponse:
        obj = await self._get(project_id, nfr_id)
        if body.category is not None:
            obj.category = body.category
        if body.description is not None:
            obj.description = body.description
        if body.priority is not None:
            obj.priority = body.priority
        if body.source_feature_id is not None:
            obj.source_feature_id = body.source_feature_id
        return NFRResponse.model_validate(obj)

    async def delete(self, project_id: uuid.UUID, nfr_id: uuid.UUID) -> None:
        obj = await self._get(project_id, nfr_id)
        await self.db.delete(obj)
