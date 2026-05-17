from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.requirements import (
    TERMINAL_STATUSES,
    AcceptanceCriteria,
    CloseReason,
    Epic,
    Feature,
    ItemStatus,
    ItemType,
    Story,
)
from app.models.user import User
from app.schemas.requirements import CloseRequest, StoryBuilderRequest, StoryCreateRequest, StoryUpdateRequest
from app.services.requirements.helpers import _next_story_prefix, _update_parent_references


class StoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_story(self, project_id: uuid.UUID, story_id: uuid.UUID) -> Story:
        result = await self.db.execute(
            select(Story)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Story.id == story_id, Epic.project_id == project_id)
            .options(selectinload(Story.acceptance_criteria))
        )
        story = result.scalar_one_or_none()
        if not story:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy story")
        return story

    async def create(self, project_id: uuid.UUID, feature_id: uuid.UUID, body: StoryCreateRequest) -> Story:
        result = await self.db.execute(
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Feature.id == feature_id, Epic.project_id == project_id)
        )
        feature = result.scalar_one_or_none()
        if not feature:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy feature")
        prefix = await _next_story_prefix(feature, self.db)
        story = Story(
            feature_id=feature.id,
            prefix=prefix,
            title=body.title,
            description=body.description,
            actor_ref=body.actor_ref,
            action_text=body.action_text,
            goal_text=body.goal_text,
            priority=body.priority,
            labels=body.labels,
            story_points=body.story_points,
        )
        self.db.add(story)
        await self.db.flush()
        _update_parent_references(feature, story.prefix, "add")
        result = await self.db.execute(
            select(Story).where(Story.id == story.id).options(selectinload(Story.acceptance_criteria))
        )
        return result.scalar_one()

    async def list(
        self,
        project_id: uuid.UUID,
        feature_id: uuid.UUID | None = None,
        item_status: ItemStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Story]:
        stmt = (
            select(Story)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Epic.project_id == project_id)
            .options(selectinload(Story.acceptance_criteria))
        )
        if feature_id:
            stmt = stmt.where(Story.feature_id == feature_id)
        if item_status:
            stmt = stmt.where(Story.status == item_status)
        stmt = stmt.order_by(Story.prefix).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get(self, project_id: uuid.UUID, story_id: uuid.UUID) -> Story:
        return await self._get_story(project_id, story_id)

    async def update(
        self, project_id: uuid.UUID, story_id: uuid.UUID, body: StoryUpdateRequest
    ) -> Story:
        story = await self._get_story(project_id, story_id)
        if body.title is not None:
            story.title = body.title
        if body.description is not None:
            story.description = body.description
        if body.actor_ref is not None:
            story.actor_ref = body.actor_ref
        if body.action_text is not None:
            story.action_text = body.action_text
        if body.goal_text is not None:
            story.goal_text = body.goal_text
        if body.status is not None:
            story.status = body.status
        if body.priority is not None:
            story.priority = body.priority
        if body.labels is not None:
            story.labels = body.labels
        if body.story_points is not None:
            story.story_points = body.story_points
        return story

    async def delete(self, project_id: uuid.UUID, story_id: uuid.UUID) -> None:
        story = await self._get_story(project_id, story_id)
        feature = await self.db.get(Feature, story.feature_id)
        if feature:
            _update_parent_references(feature, story.prefix, "remove")
        await self.db.delete(story)

    async def close(
        self, project_id: uuid.UUID, story_id: uuid.UUID, body: CloseRequest, user: User
    ) -> CloseReason:
        story = await self._get_story(project_id, story_id)
        if story.status in TERMINAL_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Story đã được đóng")
        story.status = ItemStatus(body.reason.value)
        close = CloseReason(
            item_type=ItemType.story,
            item_id=story.id,
            reason=body.reason,
            comment=body.comment,
            closed_by=user.id,
        )
        self.db.add(close)
        await self.db.flush()
        return close

    async def build(self, project_id: uuid.UUID, body: StoryBuilderRequest) -> Story:
        result = await self.db.execute(
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Feature.id == body.feature_id, Epic.project_id == project_id)
        )
        feature = result.scalar_one_or_none()
        if not feature:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy feature")
        title = f"As {body.actor_ref}, I want {body.action_text}, so that {body.goal_text}"
        prefix = await _next_story_prefix(feature, self.db)
        story = Story(
            feature_id=feature.id,
            prefix=prefix,
            title=title,
            actor_ref=body.actor_ref,
            action_text=body.action_text,
            goal_text=body.goal_text,
            priority=body.priority,
            labels=body.labels,
        )
        self.db.add(story)
        await self.db.flush()
        for i, ac in enumerate(body.acceptance_criteria):
            criteria = AcceptanceCriteria(
                story_id=story.id,
                description=ac.description,
                order=ac.order if ac.order else i,
            )
            self.db.add(criteria)
        await self.db.flush()
        _update_parent_references(feature, story.prefix, "add")
        result = await self.db.execute(
            select(Story).where(Story.id == story.id).options(selectinload(Story.acceptance_criteria))
        )
        return result.scalar_one()
