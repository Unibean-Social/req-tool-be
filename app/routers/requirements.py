import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user
from app.models.actor import Actor
from app.models.organization import OrgMember
from app.models.project import Project
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
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    EpicCreateRequest,
    EpicResponse,
    EpicTree,
    EpicUpdateRequest,
    FeatureCreateRequest,
    FeatureResponse,
    FeatureUpdateRequest,
    StoryBuilderRequest,
    StoryCreateRequest,
    StoryResponse,
    StoryUpdateRequest,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
)
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["requirements"])


# ── Shared guards ─────────────────────────────────────────────────────────────


async def _require_project_access(project_id: uuid.UUID, user: User, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    member = await db.execute(
        select(OrgMember).where(OrgMember.org_id == project.org_id, OrgMember.user_id == user.id)
    )
    if not member.scalar_one_or_none():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of this project's organization")
    return project


async def _bp12_check(project_id: uuid.UUID, title: str, db: AsyncSession) -> None:
    """BP-12: Epic title must not contain a registered actor name (whole-word, case-insensitive)."""
    result = await db.execute(select(Actor.name).where(Actor.project_id == project_id))
    actor_names = result.scalars().all()
    for name in actor_names:
        if re.search(r"\b" + re.escape(name) + r"\b", title, re.IGNORECASE):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"BP-12: Epic title contains actor name '{name}'",
            )


def _update_parent_references(parent_obj: Any, child_prefix: str, op: str) -> None:
    """BP-07: append or remove child prefix from parent.references (one level up only)."""
    refs = list(parent_obj.references or [])
    if op == "add":
        if child_prefix not in refs:
            refs.append(child_prefix)
    elif op == "remove":
        refs = [r for r in refs if r != child_prefix]
    parent_obj.references = refs


def _nfr_warning(feature: Any) -> list[str]:
    if not feature.nfr_note or not feature.nfr_note.strip():
        return ["BP-10: No non-functional requirement note provided for this feature"]
    return []


# ── Auto-prefix helpers ───────────────────────────────────────────────────────


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


# ── Epic CRUD ─────────────────────────────────────────────────────────────────


@router.post("/epics", response_model=ApiResponse[EpicResponse], status_code=status.HTTP_201_CREATED)
async def create_epic(
    project_id: uuid.UUID,
    body: EpicCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    await _bp12_check(project_id, body.title, db)
    prefix = await _next_epic_prefix(project_id, db)
    epic = Epic(
        project_id=project_id,
        prefix=prefix,
        title=body.title,
        description=body.description,
        priority=body.priority,
        labels=body.labels,
    )
    db.add(epic)
    await db.flush()
    return created(epic)


@router.get("/epics", response_model=ApiResponse[list[EpicResponse]])
async def list_epics(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Epic).where(Epic.project_id == project_id).order_by(Epic.prefix))
    return ok(result.scalars().all())


@router.get("/epics/{epic_id}", response_model=ApiResponse[EpicResponse])
async def get_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Epic not found")
    return ok(epic)


@router.patch("/epics/{epic_id}", response_model=ApiResponse[EpicResponse])
async def update_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    body: EpicUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Epic not found")
    if body.title is not None:
        await _bp12_check(project_id, body.title, db)
        epic.title = body.title
    if body.description is not None:
        epic.description = body.description
    if body.status is not None:
        epic.status = body.status
    if body.priority is not None:
        epic.priority = body.priority
    if body.labels is not None:
        epic.labels = body.labels
    return ok(epic)


@router.delete("/epics/{epic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Epic not found")
    await db.delete(epic)


@router.patch("/epics/{epic_id}/close", response_model=ApiResponse[CloseReasonResponse], status_code=status.HTTP_200_OK)
async def close_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Epic not found")
    if epic.status in TERMINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Epic is already closed")
    epic.status = ItemStatus(body.reason.value)
    close = CloseReason(
        item_type=ItemType.epic,
        item_id=epic.id,
        reason=body.reason,
        comment=body.comment,
        closed_by=user.id,
    )
    db.add(close)
    await db.flush()
    return ok(close)


# ── Feature CRUD ──────────────────────────────────────────────────────────────


@router.post("/epics/{epic_id}/features", response_model=ApiResponse[FeatureResponse], status_code=status.HTTP_201_CREATED)
async def create_feature(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    body: FeatureCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Epic not found")
    prefix = await _next_feature_prefix(epic, db)
    feature = Feature(
        epic_id=epic.id,
        prefix=prefix,
        title=body.title,
        description=body.description,
        priority=body.priority,
        labels=body.labels,
        nfr_note=body.nfr_note,
    )
    db.add(feature)
    await db.flush()
    _update_parent_references(epic, feature.prefix, "add")
    resp = FeatureResponse.model_validate(feature)
    warnings = _nfr_warning(feature)
    if warnings:
        resp = resp.model_copy(update={"warnings": warnings})
    return created(resp)


@router.get("/epics/{epic_id}/features", response_model=ApiResponse[list[FeatureResponse]])
async def list_features(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Epic).where(Epic.id == epic_id, Epic.project_id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Epic not found")
    result = await db.execute(select(Feature).where(Feature.epic_id == epic_id).order_by(Feature.prefix))
    features = result.scalars().all()
    resps = []
    for f in features:
        r = FeatureResponse.model_validate(f)
        w = _nfr_warning(f)
        resps.append(r.model_copy(update={"warnings": w}) if w else r)
    return ok(resps)


@router.get("/features/{feature_id}", response_model=ApiResponse[FeatureResponse])
async def get_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Feature)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Feature.id == feature_id, Epic.project_id == project_id)
    )
    feature = result.scalar_one_or_none()
    if not feature:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Feature not found")
    resp = FeatureResponse.model_validate(feature)
    w = _nfr_warning(feature)
    if w:
        resp = resp.model_copy(update={"warnings": w})
    return ok(resp)


@router.patch("/features/{feature_id}", response_model=ApiResponse[FeatureResponse])
async def update_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: FeatureUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Feature)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Feature.id == feature_id, Epic.project_id == project_id)
    )
    feature = result.scalar_one_or_none()
    if not feature:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Feature not found")
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
    resp = FeatureResponse.model_validate(feature)
    warnings = _nfr_warning(feature)
    if warnings:
        resp = resp.model_copy(update={"warnings": warnings})
    return ok(resp)


@router.delete("/features/{feature_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Feature)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Feature.id == feature_id, Epic.project_id == project_id)
    )
    feature = result.scalar_one_or_none()
    if not feature:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Feature not found")
    epic = await db.get(Epic, feature.epic_id)
    if epic:
        _update_parent_references(epic, feature.prefix, "remove")
    await db.delete(feature)


@router.patch("/features/{feature_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Feature)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Feature.id == feature_id, Epic.project_id == project_id)
    )
    feature = result.scalar_one_or_none()
    if not feature:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Feature not found")
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
    db.add(close)
    await db.flush()
    return ok(close)


# ── Story CRUD ────────────────────────────────────────────────────────────────


@router.post("/features/{feature_id}/stories", response_model=ApiResponse[StoryResponse], status_code=status.HTTP_201_CREATED)
async def create_story(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: StoryCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Feature)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Feature.id == feature_id, Epic.project_id == project_id)
    )
    feature = result.scalar_one_or_none()
    if not feature:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Feature not found")
    prefix = await _next_story_prefix(feature, db)
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
    )
    db.add(story)
    await db.flush()
    _update_parent_references(feature, story.prefix, "add")
    await db.refresh(story, ["acceptance_criteria"])
    return created(story)


@router.get("/features/{feature_id}/stories", response_model=ApiResponse[list[StoryResponse]])
async def list_stories(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Feature)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Feature.id == feature_id, Epic.project_id == project_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Feature not found")
    result = await db.execute(
        select(Story)
        .where(Story.feature_id == feature_id)
        .options(selectinload(Story.acceptance_criteria))
        .order_by(Story.prefix)
    )
    return ok(result.scalars().all())


@router.get("/stories/{story_id}", response_model=ApiResponse[StoryResponse])
async def get_story(
    project_id: uuid.UUID,
    story_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id == story_id, Epic.project_id == project_id)
        .options(selectinload(Story.acceptance_criteria))
    )
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found")
    return ok(story)


@router.patch("/stories/{story_id}", response_model=ApiResponse[StoryResponse])
async def update_story(
    project_id: uuid.UUID,
    story_id: uuid.UUID,
    body: StoryUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id == story_id, Epic.project_id == project_id)
        .options(selectinload(Story.acceptance_criteria))
    )
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found")
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
    return ok(story)


@router.delete("/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(
    project_id: uuid.UUID,
    story_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id == story_id, Epic.project_id == project_id)
    )
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found")
    feature = await db.get(Feature, story.feature_id)
    if feature:
        _update_parent_references(feature, story.prefix, "remove")
    await db.delete(story)


@router.patch("/stories/{story_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_story(
    project_id: uuid.UUID,
    story_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id == story_id, Epic.project_id == project_id)
    )
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found")
    if story.status in TERMINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Story is already closed")
    story.status = ItemStatus(body.reason.value)
    close = CloseReason(
        item_type=ItemType.story,
        item_id=story.id,
        reason=body.reason,
        comment=body.comment,
        closed_by=user.id,
    )
    db.add(close)
    await db.flush()
    return ok(close)


# ── Story Builder ─────────────────────────────────────────────────────────────


@router.post("/story-builder", response_model=ApiResponse[StoryResponse], status_code=status.HTTP_201_CREATED)
async def story_builder(
    project_id: uuid.UUID,
    body: StoryBuilderRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Feature)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Feature.id == body.feature_id, Epic.project_id == project_id)
    )
    feature = result.scalar_one_or_none()
    if not feature:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Feature not found")

    title = f"As {body.actor_ref}, I want {body.action_text}, so that {body.goal_text}"
    prefix = await _next_story_prefix(feature, db)
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
    db.add(story)
    await db.flush()

    for i, ac in enumerate(body.acceptance_criteria):
        criteria = AcceptanceCriteria(
            story_id=story.id,
            description=ac.description,
            order=ac.order if ac.order else i,
        )
        db.add(criteria)

    await db.flush()
    _update_parent_references(feature, story.prefix, "add")
    await db.refresh(story, ["acceptance_criteria"])
    return created(story)


# ── Task CRUD ─────────────────────────────────────────────────────────────────


@router.post("/stories/{story_id}/tasks", response_model=ApiResponse[TaskResponse], status_code=status.HTTP_201_CREATED)
async def create_task(
    project_id: uuid.UUID,
    story_id: uuid.UUID,
    body: TaskCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id == story_id, Epic.project_id == project_id)
    )
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found")
    prefix = await _next_task_prefix(story, db)
    task = Task(
        story_id=story.id,
        prefix=prefix,
        title=body.title,
        description=body.description,
        priority=body.priority,
        labels=body.labels,
    )
    db.add(task)
    await db.flush()
    _update_parent_references(story, task.prefix, "add")
    return created(task)


@router.get("/stories/{story_id}/tasks", response_model=ApiResponse[list[TaskResponse]])
async def list_tasks(
    project_id: uuid.UUID,
    story_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id == story_id, Epic.project_id == project_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found")
    result = await db.execute(select(Task).where(Task.story_id == story_id).order_by(Task.prefix))
    return ok(result.scalars().all())


@router.get("/tasks/{task_id}", response_model=ApiResponse[TaskResponse])
async def get_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Task.id == task_id, Epic.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return ok(task)


@router.patch("/tasks/{task_id}", response_model=ApiResponse[TaskResponse])
async def update_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Task.id == task_id, Epic.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    if body.title is not None:
        task.title = body.title
    if body.description is not None:
        task.description = body.description
    if body.status is not None:
        task.status = body.status
    if body.priority is not None:
        task.priority = body.priority
    if body.labels is not None:
        task.labels = body.labels
    return ok(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Task.id == task_id, Epic.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    story = await db.get(Story, task.story_id)
    if story:
        _update_parent_references(story, task.prefix, "remove")
    await db.delete(task)


@router.patch("/tasks/{task_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Task)
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Task.id == task_id, Epic.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status in TERMINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Task is already closed")
    task.status = ItemStatus(body.reason.value)
    close = CloseReason(
        item_type=ItemType.task,
        item_id=task.id,
        reason=body.reason,
        comment=body.comment,
        closed_by=user.id,
    )
    db.add(close)
    await db.flush()
    return ok(close)


# ── Hierarchy Tree ────────────────────────────────────────────────────────────


@router.get("/requirements/tree", response_model=ApiResponse[list[EpicTree]])
async def get_requirements_tree(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Epic)
        .where(Epic.project_id == project_id)
        .options(
            selectinload(Epic.features).selectinload(Feature.stories).selectinload(Story.tasks)
        )
        .order_by(Epic.prefix)
    )
    epics = result.scalars().all()
    return ok(epics)
