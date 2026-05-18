import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select
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


async def _next_epic_prefix(project_id: uuid.UUID, db: AsyncSession) -> str:
    await db.execute(select(Project).where(Project.id == project_id).with_for_update())
    max_n = await db.scalar(
        select(func.max(cast(func.substr(Epic.prefix, 2), Integer)))
        .where(Epic.project_id == project_id)
    )
    return f"E{(max_n or 0) + 1}"


async def _next_feature_prefix(epic: Epic, db: AsyncSession) -> str:
    await db.execute(select(Epic).where(Epic.id == epic.id).with_for_update())
    offset = len(epic.prefix) + 3  # skip "{prefix}.F" (2 chars) + 1 for SQL 1-based substr
    max_n = await db.scalar(
        select(func.max(cast(func.substr(Feature.prefix, offset), Integer)))
        .where(Feature.epic_id == epic.id)
    )
    return f"{epic.prefix}.F{(max_n or 0) + 1}"


async def _next_story_prefix(feature: Feature, db: AsyncSession) -> str:
    await db.execute(select(Feature).where(Feature.id == feature.id).with_for_update())
    offset = len(feature.prefix) + 3  # skip "{prefix}.S" (2 chars) + 1 for SQL 1-based substr
    max_n = await db.scalar(
        select(func.max(cast(func.substr(Story.prefix, offset), Integer)))
        .where(Story.feature_id == feature.id)
    )
    return f"{feature.prefix}.S{(max_n or 0) + 1}"


async def _next_task_prefix(story: Story, db: AsyncSession) -> str:
    await db.execute(select(Story).where(Story.id == story.id).with_for_update())
    offset = len(story.prefix) + 3  # skip "{prefix}.T" (2 chars) + 1 for SQL 1-based substr
    max_n = await db.scalar(
        select(func.max(cast(func.substr(Task.prefix, offset), Integer)))
        .where(Task.story_id == story.id)
    )
    return f"{story.prefix}.T{(max_n or 0) + 1}"
