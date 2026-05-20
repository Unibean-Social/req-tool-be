from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.requirements import Epic, Feature, ItemStatus, Story, Task
from app.schemas.staleness import StalenessWarningItem


class StalenessService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_stale_items(
        self, project_id: uuid.UUID, threshold_days: int = 7
    ) -> list[StalenessWarningItem]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=threshold_days)
        results: list[StalenessWarningItem] = []

        epics = (await self.db.execute(
            select(Epic).where(
                Epic.project_id == project_id,
                Epic.status == ItemStatus.in_progress,
                Epic.updated_at < cutoff,
            )
        )).scalars().all()
        for e in epics:
            updated = e.updated_at.replace(tzinfo=timezone.utc) if e.updated_at.tzinfo is None else e.updated_at
            results.append(StalenessWarningItem(
                item_type="epic",
                item_id=e.id,
                title=e.title,
                updated_at=updated,
                stale_days=(now - updated).days,
            ))

        features = (await self.db.execute(
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(
                Epic.project_id == project_id,
                Feature.status == ItemStatus.in_progress,
                Feature.updated_at < cutoff,
            )
        )).scalars().all()
        for f in features:
            updated = f.updated_at.replace(tzinfo=timezone.utc) if f.updated_at.tzinfo is None else f.updated_at
            results.append(StalenessWarningItem(
                item_type="feature",
                item_id=f.id,
                title=f.title,
                updated_at=updated,
                stale_days=(now - updated).days,
            ))

        stories = (await self.db.execute(
            select(Story)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(
                Epic.project_id == project_id,
                Story.status == ItemStatus.in_progress,
                Story.updated_at < cutoff,
            )
        )).scalars().all()
        for s in stories:
            updated = s.updated_at.replace(tzinfo=timezone.utc) if s.updated_at.tzinfo is None else s.updated_at
            results.append(StalenessWarningItem(
                item_type="story",
                item_id=s.id,
                title=s.title,
                updated_at=updated,
                stale_days=(now - updated).days,
            ))

        tasks = (await self.db.execute(
            select(Task)
            .join(Story, Task.story_id == Story.id)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(
                Epic.project_id == project_id,
                Task.status == ItemStatus.in_progress,
                Task.updated_at < cutoff,
            )
        )).scalars().all()
        for t in tasks:
            updated = t.updated_at.replace(tzinfo=timezone.utc) if t.updated_at.tzinfo is None else t.updated_at
            results.append(StalenessWarningItem(
                item_type="task",
                item_id=t.id,
                title=t.title,
                updated_at=updated,
                stale_days=(now - updated).days,
            ))

        results.sort(key=lambda x: x.stale_days, reverse=True)
        return results
