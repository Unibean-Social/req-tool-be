import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.requirements import TERMINAL_STATUSES, CloseReason, Epic, Feature, ItemStatus, ItemType
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    FeatureCreateRequest,
    FeatureResponse,
    FeatureUpdateRequest,
)
from app.services.requirements.helpers import get_feature_nfr_warnings, _next_feature_prefix, _update_parent_references


class FeatureService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_feature(self, project_id: uuid.UUID, feature_id: uuid.UUID) -> Feature:
        result = await self.db.execute(
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Feature.id == feature_id, Epic.project_id == project_id)
        )
        feature = result.scalar_one_or_none()
        if not feature:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Feature not found")
        return feature

    def _to_response(self, feature: Feature) -> FeatureResponse:
        resp = FeatureResponse.model_validate(feature)
        w = get_feature_nfr_warnings(feature)
        return resp.model_copy(update={"warnings": w}) if w else resp

    async def create(self, project_id: uuid.UUID, body: FeatureCreateRequest) -> FeatureResponse:
        result = await self.db.execute(
            select(Epic).where(Epic.id == body.epic_id, Epic.project_id == project_id)
        )
        epic = result.scalar_one_or_none()
        if not epic:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Epic not found")
        prefix = await _next_feature_prefix(epic, self.db)
        feature = Feature(
            epic_id=epic.id,
            prefix=prefix,
            title=body.title,
            description=body.description,
            priority=body.priority,
            labels=body.labels,
            nfr_note=body.nfr_note,
        )
        self.db.add(feature)
        await self.db.flush()
        _update_parent_references(epic, feature.prefix, "add")
        return self._to_response(feature)

    async def list(
        self,
        project_id: uuid.UUID,
        epic_id: uuid.UUID | None = None,
        item_status: ItemStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FeatureResponse]:
        stmt = (
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Epic.project_id == project_id)
        )
        if epic_id:
            stmt = stmt.where(Feature.epic_id == epic_id)
        if item_status:
            stmt = stmt.where(Feature.status == item_status)
        stmt = stmt.order_by(Feature.prefix).limit(limit).offset(offset)
        features = (await self.db.execute(stmt)).scalars().all()
        return [self._to_response(f) for f in features]

    async def get(self, project_id: uuid.UUID, feature_id: uuid.UUID) -> FeatureResponse:
        return self._to_response(await self._get_feature(project_id, feature_id))

    async def update(
        self, project_id: uuid.UUID, feature_id: uuid.UUID, body: FeatureUpdateRequest
    ) -> FeatureResponse:
        feature = await self._get_feature(project_id, feature_id)
        if body.title is not None:
            feature.title = body.title
        if body.description is not None:
            feature.description = body.description
        if body.status is not None:
            feature.status = body.status
        if body.priority is not None:
            feature.priority = body.priority
        if body.labels is not None:
            feature.labels = body.labels
        if body.nfr_note is not None:
            feature.nfr_note = body.nfr_note
        return self._to_response(feature)

    async def delete(self, project_id: uuid.UUID, feature_id: uuid.UUID) -> None:
        feature = await self._get_feature(project_id, feature_id)
        epic = await self.db.get(Epic, feature.epic_id)
        if epic:
            _update_parent_references(epic, feature.prefix, "remove")
        await self.db.delete(feature)

    async def close(
        self, project_id: uuid.UUID, feature_id: uuid.UUID, body: CloseRequest, user: User
    ) -> CloseReason:
        feature = await self._get_feature(project_id, feature_id)
        if feature.status in TERMINAL_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Feature is already closed")
        feature.status = ItemStatus(body.reason.value)
        close = CloseReason(
            item_type=ItemType.feature,
            item_id=feature.id,
            reason=body.reason,
            comment=body.comment,
            closed_by=user.id,
        )
        self.db.add(close)
        await self.db.flush()
        return close
