from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.nfr import NFR, NFRCategory, nfr_feature_links
from app.models.requirements import Epic, Feature, Priority
from app.schemas.nfr import NFRCreateRequest, NFRResponse, NFRUpdateRequest


class NFRService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _to_response(self, obj: NFR) -> NFRResponse:
        feature_ids = [f.id for f in obj.features]
        return NFRResponse.model_validate(obj).model_copy(update={"feature_ids": feature_ids})

    async def _get(self, project_id: uuid.UUID, nfr_id: uuid.UUID) -> NFR:
        result = await self.db.execute(
            select(NFR)
            .where(NFR.id == nfr_id, NFR.project_id == project_id)
            .options(selectinload(NFR.features))
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy NFR")
        return obj

    async def _sync_features(self, obj: NFR, feature_ids: list[uuid.UUID], project_id: uuid.UUID) -> None:
        if feature_ids:
            # Batch validate: all features must belong to this project (via Epic)
            found = (await self.db.execute(
                select(Feature.id)
                .join(Epic, Feature.epic_id == Epic.id)
                .where(Feature.id.in_(feature_ids), Epic.project_id == project_id)
            )).scalars().all()
            missing = set(feature_ids) - set(found)
            if missing:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Không tìm thấy feature: {missing}")

        await self.db.execute(
            delete(nfr_feature_links).where(nfr_feature_links.c.nfr_id == obj.id)
        )
        for fid in feature_ids:
            await self.db.execute(
                nfr_feature_links.insert().values(nfr_id=obj.id, feature_id=fid)
            )

    async def create(self, project_id: uuid.UUID, body: NFRCreateRequest) -> NFRResponse:
        obj = NFR(
            project_id=project_id,
            category=body.category,
            description=body.description,
            priority=body.priority,
        )
        self.db.add(obj)
        await self.db.flush()
        if body.feature_ids:
            await self._sync_features(obj, body.feature_ids, project_id)
        await self.db.refresh(obj, ["features"])
        return self._to_response(obj)

    async def list(
        self,
        project_id: uuid.UUID,
        category: NFRCategory | None = None,
        priority: Priority | None = None,
    ) -> list[NFRResponse]:
        stmt = (
            select(NFR)
            .where(NFR.project_id == project_id)
            .options(selectinload(NFR.features))
        )
        if category is not None:
            stmt = stmt.where(NFR.category == category)
        if priority is not None:
            stmt = stmt.where(NFR.priority == priority)
        stmt = stmt.order_by(NFR.created_at)
        result = await self.db.execute(stmt)
        return [self._to_response(n) for n in result.scalars().all()]

    async def get(self, project_id: uuid.UUID, nfr_id: uuid.UUID) -> NFRResponse:
        return self._to_response(await self._get(project_id, nfr_id))

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
        if body.feature_ids is not None:
            await self._sync_features(obj, body.feature_ids, project_id)
            await self.db.refresh(obj, ["features"])
        return self._to_response(obj)

    async def delete(self, project_id: uuid.UUID, nfr_id: uuid.UUID) -> None:
        obj = await self._get(project_id, nfr_id)
        await self.db.delete(obj)

    async def add_feature_link(
        self, project_id: uuid.UUID, nfr_id: uuid.UUID, feature_id: uuid.UUID
    ) -> NFRResponse:
        obj = await self._get(project_id, nfr_id)
        feature = await self.db.scalar(
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Feature.id == feature_id, Epic.project_id == project_id)
        )
        if not feature:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy feature")
        await self.db.execute(
            pg_insert(nfr_feature_links)
            .values(nfr_id=obj.id, feature_id=feature_id)
            .on_conflict_do_nothing()
        )
        await self.db.refresh(obj, ["features"])
        return self._to_response(obj)

    async def remove_feature_link(
        self, project_id: uuid.UUID, nfr_id: uuid.UUID, feature_id: uuid.UUID
    ) -> None:
        await self._get(project_id, nfr_id)
        result = await self.db.execute(
            delete(nfr_feature_links).where(
                nfr_feature_links.c.nfr_id == nfr_id,
                nfr_feature_links.c.feature_id == feature_id,
            )
        )
        if result.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Liên kết không tồn tại")
