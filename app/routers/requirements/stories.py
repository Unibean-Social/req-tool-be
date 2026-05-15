import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user
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
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    StoryBuilderRequest,
    StoryCreateRequest,
    StoryResponse,
    StoryUpdateRequest,
)
from app.schemas.response import ApiResponse

from ._helpers import _next_story_prefix, _require_project_access, _update_parent_references

router = APIRouter(prefix="/projects/{project_id}", tags=["stories"])


@router.post("/stories", response_model=ApiResponse[StoryResponse], status_code=status.HTTP_201_CREATED)
async def create_story(
    project_id: uuid.UUID,
    body: StoryCreateRequest,
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
        story_points=body.story_points,
    )
    db.add(story)
    await db.flush()
    _update_parent_references(feature, story.prefix, "add")
    result = await db.execute(
        select(Story).where(Story.id == story.id).options(selectinload(Story.acceptance_criteria))
    )
    story = result.scalar_one()
    return created(story)


@router.get("/stories", response_model=ApiResponse[list[StoryResponse]])
async def list_stories(
    project_id: uuid.UUID,
    feature_id: uuid.UUID | None = Query(None),
    item_status: ItemStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
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
    return ok((await db.execute(stmt)).scalars().all())


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
    if body.story_points is not None:
        story.story_points = body.story_points
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
    result = await db.execute(
        select(Story).where(Story.id == story.id).options(selectinload(Story.acceptance_criteria))
    )
    story = result.scalar_one()
    return created(story)
