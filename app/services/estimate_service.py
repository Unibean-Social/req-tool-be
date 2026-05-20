from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.requirements import Story
from app.models.story_estimate import StoryEstimate
from app.schemas.estimate import EstimateItemResponse, EstimateListResponse

FIBONACCI = [1, 2, 3, 5, 8, 13, 21, 40, 100]
VALID_VALUES = {"1", "2", "3", "5", "8", "13", "21", "40", "100", "?"}


def nearest_fibonacci(avg: float) -> int:
    return min(FIBONACCI, key=lambda n: abs(n - avg))


class EstimateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_story(self, project_id: uuid.UUID, story_id: uuid.UUID) -> Story:
        from app.models.requirements import Epic, Feature
        result = await self.db.execute(
            select(Story)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Story.id == story_id, Epic.project_id == project_id)
        )
        story = result.scalar_one_or_none()
        if not story:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy story")
        return story

    async def upsert(
        self, project_id: uuid.UUID, story_id: uuid.UUID, voter_id: uuid.UUID, value: str
    ) -> dict:
        story = await self._get_story(project_id, story_id)

        await self.db.execute(
            pg_insert(StoryEstimate)
            .values(story_id=story_id, voter_id=voter_id, value=value)
            .on_conflict_do_update(
                constraint="uq_story_estimates_story_voter",
                set_={"value": value, "updated_at": sa.func.now()},
            )
        )
        # Flush to commit upsert, then expire identity map so re-select hits DB not cache
        await self.db.flush()
        self.db.expire_all()

        estimates = (await self.db.execute(
            select(StoryEstimate).where(StoryEstimate.story_id == story_id)
        )).scalars().all()

        numeric = [int(e.value) for e in estimates if e.value != "?"]
        if numeric:
            story.story_points = nearest_fibonacci(sum(numeric) / len(numeric))
        else:
            # All votes are "?" — reset to None to reflect unresolved consensus
            story.story_points = None

        await self.db.flush()
        return self._build_response(estimates, story)

    async def list(self, project_id: uuid.UUID, story_id: uuid.UUID) -> dict:
        story = await self._get_story(project_id, story_id)
        estimates = (await self.db.execute(
            select(StoryEstimate).where(StoryEstimate.story_id == story_id)
        )).scalars().all()
        return self._build_response(estimates, story)

    def _build_response(self, estimates: list[StoryEstimate], story: Story) -> EstimateListResponse:
        numeric = [int(e.value) for e in estimates if e.value != "?"]
        average = round(sum(numeric) / len(numeric), 1) if numeric else None
        return EstimateListResponse(
            estimates=[
                EstimateItemResponse(id=e.id, voter_id=e.voter_id, value=e.value, created_at=e.created_at, updated_at=e.updated_at)
                for e in estimates
            ],
            average=average,
            story_points=story.story_points,
        )
