import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user
from app.models.requirements import TERMINAL_STATUSES, CloseReason, Epic, Feature, ItemStatus, ItemType
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    FeatureCreateRequest,
    FeatureResponse,
    FeatureUpdateRequest,
)
from app.schemas.response import ApiResponse

from ._helpers import _nfr_warning, _next_feature_prefix, _require_project_access, _update_parent_references

router = APIRouter(prefix="/projects/{project_id}", tags=["features"])


@router.post("/features", response_model=ApiResponse[FeatureResponse], status_code=status.HTTP_201_CREATED)
async def create_feature(
    project_id: uuid.UUID,
    body: FeatureCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Epic).where(Epic.id == body.epic_id, Epic.project_id == project_id))
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


@router.get("/features", response_model=ApiResponse[list[FeatureResponse]])
async def list_features(
    project_id: uuid.UUID,
    epic_id: uuid.UUID | None = Query(None),
    item_status: ItemStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    stmt = (
        select(Feature)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id)
    )
    if epic_id:
        stmt = stmt.where(Feature.epic_id == epic_id)
    if item_status:
        stmt = stmt.where(Feature.status == item_status)
    stmt = stmt.order_by(Feature.prefix).limit(limit).offset(offset)
    features = (await db.execute(stmt)).scalars().all()
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
