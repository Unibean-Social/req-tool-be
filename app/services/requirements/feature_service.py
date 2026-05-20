from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.requirements import TERMINAL_STATUSES, CloseReason, Epic, Feature, ItemStatus, ItemType, Story
from app.models.user import User

if TYPE_CHECKING:
    from app.services.github_service import GithubService
from app.schemas.requirements import (
    CloseRequest,
    FeatureCreateRequest,
    FeatureResponse,
    FeatureUpdateRequest,
)
from app.services.requirements.helpers import _next_feature_prefix, _update_parent_references


class FeatureService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_feature(self, project_id: uuid.UUID, feature_id: uuid.UUID) -> Feature:
        result = await self.db.execute(
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Feature.id == feature_id, Epic.project_id == project_id)
            .options(selectinload(Feature.stories))
        )
        feature = result.scalar_one_or_none()
        if not feature:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy feature")
        return feature

    def _to_response(self, feature: Feature) -> FeatureResponse:
        resp = FeatureResponse.model_validate(feature)
        stories = feature.stories if feature.stories is not None else []
        open_stories = [s for s in stories if s.status not in TERMINAL_STATUSES]
        return resp.model_copy(update={
            "total_story_points": sum(s.story_points or 0 for s in open_stories),
            "total_business_value": sum(s.business_value or 0 for s in open_stories),
            "story_count": len(open_stories),
        })

    async def create(
        self, project_id: uuid.UUID, epic_id: uuid.UUID, body: FeatureCreateRequest
    ) -> FeatureResponse:
        result = await self.db.execute(
            select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id)
        )
        epic = result.scalar_one_or_none()
        if not epic:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy epic")
        prefix = await _next_feature_prefix(epic, self.db)
        feature = Feature(
            epic_id=epic.id,
            prefix=prefix,
            title=body.title,
            description=body.description,
            priority=body.priority,
            labels=body.labels,
        )
        self.db.add(feature)
        await self.db.flush()
        feature_id = feature.id
        _update_parent_references(epic, feature.prefix, "add")
        return self._to_response(await self._get_feature(project_id, feature_id))

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
            .options(selectinload(Feature.stories))
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
        await self.db.flush()
        return self._to_response(await self._get_feature(project_id, feature_id))

    async def delete(self, project_id: uuid.UUID, feature_id: uuid.UUID) -> None:
        feature = await self._get_feature(project_id, feature_id)
        epic = await self.db.get(Epic, feature.epic_id)
        if epic:
            _update_parent_references(epic, feature.prefix, "remove")
        await self.db.delete(feature)

    async def close(
        self,
        project_id: uuid.UUID,
        feature_id: uuid.UUID,
        body: CloseRequest,
        user: User,
        github_service: GithubService | None = None,
    ) -> CloseReason:
        feature = await self._get_feature(project_id, feature_id)
        if feature.status in TERMINAL_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Feature đã được đóng")
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
        if github_service is not None:
            await github_service.post_close_comment(
                project_id, ItemType.feature, feature.id, body.reason.value, body.comment
            )
        return close
