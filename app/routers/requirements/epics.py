import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user
from app.models.requirements import TERMINAL_STATUSES, CloseReason, Epic, Feature, ItemStatus, ItemType, Story, Task
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    EpicCreateRequest,
    EpicResponse,
    EpicTree,
    EpicUpdateRequest,
)
from app.schemas.response import ApiResponse

from ._helpers import _bp12_check, _next_epic_prefix, _require_project_access

router = APIRouter(prefix="/projects/{project_id}", tags=["epics"])


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
    return ok(result.scalars().all())
