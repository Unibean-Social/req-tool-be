import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, case, cast, func, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.database import get_db
from app.deps import current_user
from app.core.guards import require_project_access
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
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["health"])

_LABEL_PREFIXES = ("type:", "status:", "priority:")




# ── Label helpers ──────────────────────────────────────────────────────────────


def _label_complete_filter(labels_col):
    j = cast(labels_col, JSONB)
    return and_(*(
        j.op("@?")(literal_column(f"'$[*] ? (@ starts with \"{p}\")'::jsonpath"))
        for p in _LABEL_PREFIXES
    ))


# ── Health Score ───────────────────────────────────────────────────────────────


@router.get("/health", response_model=ApiResponse[dict])
async def get_health(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(project_id, user, db)

    r = await db.execute(
        select(
            func.count(Epic.id).label("total"),
            func.count(Epic.id).filter(_label_complete_filter(Epic.labels)).label("labeled"),
        ).where(Epic.project_id == project_id)
    )
    _epic = r.one()
    epic_total, epic_labeled = _epic.total or 0, _epic.labeled or 0

    # ── Feature: label completeness ───────────────────────────────────────────
    r = await db.execute(
        select(
            func.count(Feature.id).label("total"),
            func.count(Feature.id).filter(_label_complete_filter(Feature.labels)).label("labeled"),
        )
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id)
    )
    _feat = r.one()
    feature_total, feature_labeled = _feat.total or 0, _feat.labeled or 0

    r = await db.execute(
        select(
            func.count(func.distinct(Story.id)).label("total"),
            func.count(func.distinct(
                case((_label_complete_filter(Story.labels), Story.id))
            )).label("labeled"),
            func.count(func.distinct(AcceptanceCriteria.story_id)).label("with_ac"),
        )
        .outerjoin(AcceptanceCriteria, AcceptanceCriteria.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id)
    )
    _story = r.one()
    story_total = _story.total or 0
    story_labeled = _story.labeled or 0
    stories_with_ac = _story.with_ac or 0
    ac_coverage = 100 if story_total == 0 else round(stories_with_ac / story_total * 100)

    r = await db.execute(
        select(
            func.count(Task.id).label("total"),
            func.count(Task.id).filter(_label_complete_filter(Task.labels)).label("labeled"),
        )
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id)
    )
    _task = r.one()
    task_total, task_labeled = _task.total or 0, _task.labeled or 0

    total_items = epic_total + feature_total + story_total + task_total
    total_labeled = epic_labeled + feature_labeled + story_labeled + task_labeled
    label_completeness = 100 if total_items == 0 else round(total_labeled / total_items * 100)

    r = await db.execute(
        select(
            func.count(func.distinct(Epic.id)).label("closed"),
            func.count(func.distinct(CloseReason.item_id)).label("with_reason"),
        )
        .outerjoin(CloseReason, and_(CloseReason.item_id == Epic.id, CloseReason.item_type == ItemType.epic))
        .where(Epic.project_id == project_id, Epic.status.in_(TERMINAL_STATUSES))
    )
    _eh = r.one()
    epic_closed, epic_with_reason = _eh.closed or 0, _eh.with_reason or 0

    r = await db.execute(
        select(
            func.count(func.distinct(Feature.id)).label("closed"),
            func.count(func.distinct(CloseReason.item_id)).label("with_reason"),
        )
        .outerjoin(CloseReason, and_(CloseReason.item_id == Feature.id, CloseReason.item_type == ItemType.feature))
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id, Feature.status.in_(TERMINAL_STATUSES))
    )
    _fh = r.one()
    feature_closed, feature_with_reason = _fh.closed or 0, _fh.with_reason or 0

    r = await db.execute(
        select(
            func.count(func.distinct(Story.id)).label("closed"),
            func.count(func.distinct(CloseReason.item_id)).label("with_reason"),
        )
        .outerjoin(CloseReason, and_(CloseReason.item_id == Story.id, CloseReason.item_type == ItemType.story))
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id, Story.status.in_(TERMINAL_STATUSES))
    )
    _sh = r.one()
    story_closed, story_with_reason = _sh.closed or 0, _sh.with_reason or 0

    r = await db.execute(
        select(
            func.count(func.distinct(Task.id)).label("closed"),
            func.count(func.distinct(CloseReason.item_id)).label("with_reason"),
        )
        .outerjoin(CloseReason, and_(CloseReason.item_id == Task.id, CloseReason.item_type == ItemType.task))
        .join(Story, Task.story_id == Story.id)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id, Task.status.in_(TERMINAL_STATUSES))
    )
    _th = r.one()
    task_closed, task_with_reason = _th.closed or 0, _th.with_reason or 0

    total_closed = epic_closed + feature_closed + story_closed + task_closed
    total_with_reason = epic_with_reason + feature_with_reason + story_with_reason + task_with_reason
    close_hygiene = 100 if total_closed == 0 else round(total_with_reason / total_closed * 100)

    overall = round((ac_coverage + label_completeness + close_hygiene) / 3)

    return ok({
        "ac_coverage": ac_coverage,
        "label_completeness": label_completeness,
        "close_hygiene": close_hygiene,
        "overall": overall,
        "item_counts": {
            "epics": epic_total,
            "features": feature_total,
            "stories": story_total,
            "tasks": task_total,
        },
    })


# ── Per-item Audit ─────────────────────────────────────────────────────────────


@router.get("/requirements/{item_type}/{item_id}/audit", response_model=ApiResponse[list[dict]])
async def audit_item(
    project_id: uuid.UUID,
    item_type: ItemType,
    item_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(project_id, user, db)

    # Load item
    if item_type == ItemType.epic:
        r = await db.execute(select(Epic).where(Epic.id == item_id, Epic.project_id == project_id))
        item = r.scalar_one_or_none()
    elif item_type == ItemType.feature:
        r = await db.execute(
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Feature.id == item_id, Epic.project_id == project_id)
        )
        item = r.scalar_one_or_none()
    elif item_type == ItemType.story:
        r = await db.execute(
            select(Story)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Story.id == item_id, Epic.project_id == project_id)
        )
        item = r.scalar_one_or_none()
    else:  # task
        r = await db.execute(
            select(Task)
            .join(Story, Task.story_id == Story.id)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Task.id == item_id, Epic.project_id == project_id)
        )
        item = r.scalar_one_or_none()

    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{item_type.value} not found")

    checks: list[dict] = []

    # BP-05: closed item must have CloseReason
    if item.status in TERMINAL_STATUSES:
        cr = await db.execute(
            select(CloseReason).where(
                CloseReason.item_type == item_type,
                CloseReason.item_id == item_id,
            )
        )
        has_reason = cr.scalar_one_or_none() is not None
        checks.append({
            "rule": "BP-05",
            "pass": has_reason,
            "detail": "Closed item has a CloseReason record" if has_reason else "Closed item missing CloseReason",
        })
    else:
        checks.append({"rule": "BP-05", "pass": True, "detail": "Item is not closed"})

    # Label completeness
    labels = list(item.labels or [])
    missing_prefixes = [p for p in _LABEL_PREFIXES if not any(l.startswith(p) for l in labels)]
    checks.append({
        "rule": "LABEL_COMPLETE",
        "pass": len(missing_prefixes) == 0,
        "detail": (
            "All label categories present"
            if not missing_prefixes
            else f"Missing categories: {', '.join(missing_prefixes)}"
        ),
    })

    # Type-specific rules
    if item_type == ItemType.epic:
        actors_r = await db.execute(select(Actor.name).where(Actor.project_id == project_id))
        actor_names = actors_r.scalars().all()
        violated = next(
            (n for n in actor_names if re.search(r"\b" + re.escape(n) + r"\b", item.title, re.IGNORECASE)),
            None,
        )
        checks.append({
            "rule": "BP-12",
            "pass": violated is None,
            "detail": "No actor name in title" if violated is None else f"Title contains actor name '{violated}'",
        })

    elif item_type == ItemType.story:
        ac_count = await db.scalar(
            select(func.count(AcceptanceCriteria.id)).where(AcceptanceCriteria.story_id == item_id)
        ) or 0
        checks.append({
            "rule": "BP-03",
            "pass": ac_count > 0,
            "detail": f"{ac_count} acceptance criteria" if ac_count > 0 else "No acceptance criteria (BP-03 requires ≥1)",
        })

    elif item_type == ItemType.feature:
        has_nfr = bool(item.nfr_note and item.nfr_note.strip())
        checks.append({
            "rule": "BP-10",
            "pass": has_nfr,
            "detail": "NFR note is present" if has_nfr else "Missing non-functional requirement note",
        })

    return ok(checks)
