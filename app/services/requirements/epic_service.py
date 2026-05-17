from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.actor import Actor
from app.models.requirements import (
    TERMINAL_STATUSES,
    AcceptanceCriteria,
    CloseReason,
    Epic,
    Feature,
    ItemStatus,
    ItemType,
    Story,
    Task,
)
from app.models.user import User
from app.schemas.requirements import CloseRequest, EpicCreateRequest, EpicResponse, EpicUpdateRequest
from app.schemas.requirement_model import RequirementModelResponse
from app.services.requirements.helpers import check_epic_title_excludes_actors, _next_epic_prefix


class EpicService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _to_response(self, epic: Epic) -> EpicResponse:
        resp = EpicResponse.model_validate(epic)
        features = epic.features if epic.features is not None else []
        open_stories_per_feature = [
            [s for s in f.stories if s.status not in TERMINAL_STATUSES]
            for f in features
        ]
        return resp.model_copy(update={
            "total_story_points": sum(s.story_points or 0 for stories in open_stories_per_feature for s in stories),
            "total_business_value": sum(s.business_value or 0 for stories in open_stories_per_feature for s in stories),
            "feature_count": len(features),
            "story_count": sum(len(stories) for stories in open_stories_per_feature),
        })

    async def _load_epic(self, project_id: uuid.UUID, epic_id: uuid.UUID) -> Epic:
        result = await self.db.execute(
            select(Epic)
            .where(Epic.id == epic_id, Epic.project_id == project_id)
            .options(selectinload(Epic.features).selectinload(Feature.stories))
        )
        epic = result.scalar_one_or_none()
        if not epic:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy epic")
        return epic

    async def create(
        self, project_id: uuid.UUID, body: EpicCreateRequest, user: User, actor_id: uuid.UUID | None = None
    ) -> EpicResponse:
        await check_epic_title_excludes_actors(project_id, body.title, self.db)
        prefix = await _next_epic_prefix(project_id, self.db)
        epic = Epic(
            project_id=project_id,
            actor_id=actor_id,
            prefix=prefix,
            title=body.title,
            description=body.description,
            priority=body.priority,
            labels=body.labels,
        )
        self.db.add(epic)
        await self.db.flush()
        # new epic has no features yet — rollup is 0
        return EpicResponse.model_validate(epic)

    async def list(self, project_id: uuid.UUID) -> list[EpicResponse]:
        result = await self.db.execute(
            select(Epic)
            .where(Epic.project_id == project_id)
            .options(selectinload(Epic.features).selectinload(Feature.stories))
            .order_by(Epic.prefix)
        )
        return [self._to_response(e) for e in result.scalars().all()]

    async def get(self, project_id: uuid.UUID, epic_id: uuid.UUID) -> EpicResponse:
        return self._to_response(await self._load_epic(project_id, epic_id))

    async def update(self, project_id: uuid.UUID, epic_id: uuid.UUID, body: EpicUpdateRequest) -> EpicResponse:
        epic = await self._load_epic(project_id, epic_id)
        if body.title is not None:
            await check_epic_title_excludes_actors(project_id, body.title, self.db)
            epic.title = body.title
        if body.description is not None:
            epic.description = body.description
        if body.status is not None:
            epic.status = body.status
        if body.priority is not None:
            epic.priority = body.priority
        if body.labels is not None:
            epic.labels = body.labels
        return self._to_response(epic)

    async def delete(self, project_id: uuid.UUID, epic_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id)
        )
        epic = result.scalar_one_or_none()
        if not epic:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy epic")
        await self.db.delete(epic)

    async def close(
        self, project_id: uuid.UUID, epic_id: uuid.UUID, body: CloseRequest, user: User
    ) -> CloseReason:
        result = await self.db.execute(
            select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id)
        )
        epic = result.scalar_one_or_none()
        if not epic:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy epic")
        if epic.status in TERMINAL_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Epic đã được đóng")
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

    async def get_requirement_model(
        self, project_id: uuid.UUID, actor_id: uuid.UUID
    ) -> RequirementModelResponse:
        actor_result = await self.db.execute(
            select(Actor).where(Actor.id == actor_id, Actor.project_id == project_id)
        )
        actor = actor_result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy actor")

        epic_result = await self.db.execute(
            select(Epic)
            .where(Epic.actor_id == actor_id, Epic.project_id == project_id)
            .options(
                selectinload(Epic.features).selectinload(Feature.stories).selectinload(
                    Story.acceptance_criteria
                )
            )
            .order_by(Epic.prefix)
        )
        epics = list(epic_result.scalars().unique().all())

        features: list[Feature] = []
        stories: list[Story] = []
        for epic in epics:
            for feature in epic.features:
                features.append(feature)
                stories.extend(feature.stories)

        return RequirementModelResponse(
            actor=actor,
            epics=epics,
            features=features,
            user_stories=stories,
        )
