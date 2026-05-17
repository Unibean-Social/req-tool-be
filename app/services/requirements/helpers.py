import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor
from app.models.project import Project
from app.models.requirements import Epic, Feature, Story, Task


async def check_epic_title_excludes_actors(project_id: uuid.UUID, title: str, db: AsyncSession) -> None:
    result = await db.execute(select(Actor.name).where(Actor.project_id == project_id))
    actor_names = result.scalars().all()
    for name in actor_names:
        if re.search(r"\b" + re.escape(name) + r"\b", title, re.IGNORECASE):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Tiêu đề epic không được chứa tên actor '{name}'",
            )


def _update_parent_references(parent_obj: Any, child_prefix: str, op: str) -> None:
    refs = list(parent_obj.references or [])
    if op == "add":
        if child_prefix not in refs:
            refs.append(child_prefix)
    elif op == "remove":
        refs = [r for r in refs if r != child_prefix]
    parent_obj.references = refs


def get_feature_nfr_warnings(feature: Any) -> list[str]:
    if not feature.nfr_note or not feature.nfr_note.strip():
        return ["Feature này chưa có ghi chú về yêu cầu phi chức năng"]
    return []


async def _next_epic_prefix(project_id: uuid.UUID, db: AsyncSession) -> str:
    await db.execute(select(Project).where(Project.id == project_id).with_for_update())
    count = await db.scalar(select(func.count(Epic.id)).where(Epic.project_id == project_id))
    return f"E{(count or 0) + 1}"


async def _next_feature_prefix(epic: Epic, db: AsyncSession) -> str:
    await db.execute(select(Epic).where(Epic.id == epic.id).with_for_update())
    count = await db.scalar(select(func.count(Feature.id)).where(Feature.epic_id == epic.id))
    return f"{epic.prefix}.F{(count or 0) + 1}"


async def _next_story_prefix(feature: Feature, db: AsyncSession) -> str:
    await db.execute(select(Feature).where(Feature.id == feature.id).with_for_update())
    count = await db.scalar(select(func.count(Story.id)).where(Story.feature_id == feature.id))
    return f"{feature.prefix}.S{(count or 0) + 1}"


async def _next_task_prefix(story: Story, db: AsyncSession) -> str:
    await db.execute(select(Story).where(Story.id == story.id).with_for_update())
    count = await db.scalar(select(func.count(Task.id)).where(Task.story_id == story.id))
    return f"{story.prefix}.T{(count or 0) + 1}"
