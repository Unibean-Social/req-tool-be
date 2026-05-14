import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.crypto import decrypt_token
from app.core.github_client import GithubClient
from app.core.responses import ok
from app.core.sync_formatter import format_item
from app.database import get_db
from app.deps import current_user
from app.models.github_connection import GithubConnection
from app.models.organization import OrgMember
from app.models.project import Project
from app.models.requirements import Epic, Feature, ItemType, Story, Task
from app.models.sync import GithubItem, SyncLog, SyncLogStatus, SyncOperation, SyncQueue, SyncQueueStatus
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.sync import (
    PushReport,
    PushResultItem,
    StageRequest,
    SyncLogResponse,
    SyncQueueResponse,
)

router = APIRouter(tags=["sync"])

_TYPE_ORDER = {"epic": 0, "feature": 1, "story": 2, "task": 3}


# ── Guards ─────────────────────────────────────────────────────────────────────


async def _require_project_member(project_id: uuid.UUID, user: User, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail="Project not found")
    member = await db.execute(
        select(OrgMember).where(OrgMember.org_id == project.org_id, OrgMember.user_id == user.id)
    )
    if not member.scalar_one_or_none():
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, detail="Not a member of this project's organization")
    return project


async def _require_connection(project_id: uuid.UUID, db: AsyncSession) -> GithubConnection:
    result = await db.execute(select(GithubConnection).where(GithubConnection.project_id == project_id))
    conn = result.scalar_one_or_none()
    if not conn or not conn.access_token:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="No GitHub connection — connect the project first")
    return conn


# ── Item loader ────────────────────────────────────────────────────────────────


async def _load_item(item_type: str, item_id: uuid.UUID, project_id: uuid.UUID, db: AsyncSession) -> Any:
    if item_type == "epic":
        q = select(Epic).where(Epic.id == item_id, Epic.project_id == project_id)
    elif item_type == "feature":
        q = (
            select(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Feature.id == item_id, Epic.project_id == project_id)
        )
    elif item_type == "story":
        q = (
            select(Story)
            .options(selectinload(Story.acceptance_criteria))
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Story.id == item_id, Epic.project_id == project_id)
        )
    elif item_type == "task":
        q = (
            select(Task)
            .join(Story, Task.story_id == Story.id)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Task.id == item_id, Epic.project_id == project_id)
        )
    else:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail=f"Unknown item_type: {item_type}")

    result = await db.execute(q)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"{item_type} {item_id} not found in project")
    return item


async def _get_parent_id(item_type: str, item: Any) -> uuid.UUID | None:
    """Return the direct parent's item_id for dependency check, or None for epics."""
    if item_type == "epic":
        return None
    if item_type == "feature":
        return item.epic_id
    if item_type == "story":
        return item.feature_id
    if item_type == "task":
        return item.story_id
    return None


def _parent_type(item_type: str) -> str | None:
    return {"feature": "epic", "story": "feature", "task": "story"}.get(item_type)


# ── Stage ──────────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/sync/stage",
    response_model=ApiResponse[list[SyncQueueResponse]],
    status_code=http_status.HTTP_200_OK,
)
async def stage_items(
    project_id: uuid.UUID,
    body: StageRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)

    for req_item in body.items:
        item = await _load_item(req_item.item_type.value, req_item.item_id, project_id, db)
        snapshot = format_item(item, req_item.item_type.value)

        # Determine operation: create if no GithubItem exists, else update
        gi_result = await db.execute(
            select(GithubItem).where(
                GithubItem.item_type == req_item.item_type,
                GithubItem.item_id == req_item.item_id,
            )
        )
        operation = SyncOperation.update if gi_result.scalar_one_or_none() else SyncOperation.create

        # Upsert: update existing queue row or insert new
        existing = await db.execute(
            select(SyncQueue).where(
                SyncQueue.project_id == project_id,
                SyncQueue.item_type == req_item.item_type,
                SyncQueue.item_id == req_item.item_id,
            )
        )
        queue_row = existing.scalar_one_or_none()
        if queue_row:
            queue_row.body_snapshot = snapshot
            queue_row.operation = operation
            queue_row.status = SyncQueueStatus.pending
        else:
            queue_row = SyncQueue(
                project_id=project_id,
                item_type=req_item.item_type,
                item_id=req_item.item_id,
                operation=operation,
                body_snapshot=snapshot,
                status=SyncQueueStatus.pending,
            )
            db.add(queue_row)

    await db.flush()

    rows = await db.execute(
        select(SyncQueue).where(SyncQueue.project_id == project_id).order_by(SyncQueue.created_at)
    )
    return ok([SyncQueueResponse.model_validate(r) for r in rows.scalars().all()])


# ── Pending ────────────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/sync/pending",
    response_model=ApiResponse[list[SyncQueueResponse]],
)
async def get_pending(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    rows = await db.execute(
        select(SyncQueue)
        .where(SyncQueue.project_id == project_id)
        .order_by(SyncQueue.created_at)
    )
    return ok([SyncQueueResponse.model_validate(r) for r in rows.scalars().all()])


# ── Unstage ────────────────────────────────────────────────────────────────────


@router.delete(
    "/projects/{project_id}/sync/pending/{queue_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def unstage_item(
    project_id: uuid.UUID,
    queue_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    result = await db.execute(
        select(SyncQueue).where(SyncQueue.id == queue_id, SyncQueue.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail="Queue entry not found")
    await db.delete(row)


# ── Push ───────────────────────────────────────────────────────────────────────


async def _push_one(
    row: SyncQueue,
    gh: GithubClient,
    repo_owner: str,
    repo_name: str,
    db: AsyncSession,
) -> PushResultItem:
    snapshot = row.body_snapshot
    item_type = row.item_type.value
    item_id = row.item_id

    # Label validation — fail fast before parent check
    labels = snapshot.get("github_labels") or []
    missing_cats = [p for p in ("type:", "status:", "priority:") if not any(l.startswith(p) for l in labels)]
    if missing_cats:
        row.status = SyncQueueStatus.failed
        msg = f"Missing label categories: {', '.join(missing_cats)}"
        log = SyncLog(
            project_id=row.project_id,
            sync_queue_id=row.id,
            item_type=row.item_type,
            item_id=item_id,
            operation=row.operation,
            status=SyncLogStatus.failed,
            error_code="LABEL_INCOMPLETE",
            error_message=msg,
        )
        db.add(log)
        return PushResultItem(
            item_type=row.item_type,
            item_id=item_id,
            github_issue_number=None,
            github_issue_url=None,
            error_code="LABEL_INCOMPLETE",
            error_message=msg,
        )

    # Parent dependency check
    p_type = _parent_type(item_type)
    if p_type:
        # Determine parent id by loading a minimal view of the item
        parent_item = await _get_parent_for_push(item_type, item_id, db)
        if parent_item is not None:
            gi = await db.execute(
                select(GithubItem).where(
                    GithubItem.item_type == ItemType(p_type),
                    GithubItem.item_id == parent_item,
                )
            )
            if not gi.scalar_one_or_none():
                row.status = SyncQueueStatus.failed
                log = SyncLog(
                    project_id=row.project_id,
                    sync_queue_id=row.id,
                    item_type=row.item_type,
                    item_id=item_id,
                    operation=row.operation,
                    status=SyncLogStatus.failed,
                    error_code="MISSING_PARENT_ISSUE",
                    error_message=f"Parent {p_type} has no GitHub issue — push parent first",
                )
                db.add(log)
                return PushResultItem(
                    item_type=row.item_type,
                    item_id=item_id,
                    github_issue_number=None,
                    github_issue_url=None,
                    error_code="MISSING_PARENT_ISSUE",
                    error_message=log.error_message,
                )

    # Check for existing GithubItem
    gi_result = await db.execute(
        select(GithubItem).where(GithubItem.item_type == row.item_type, GithubItem.item_id == item_id)
    )
    existing_gi = gi_result.scalar_one_or_none()

    queue_id = row.id  # capture before any db.delete(row) — row.id still accessible but FK would be gone
    try:
        if row.operation == SyncOperation.close:
            if existing_gi:
                await gh.patch(
                    f"/repos/{repo_owner}/{repo_name}/issues/{existing_gi.github_issue_number}",
                    json={"state": "closed"},
                )
            issue_number = existing_gi.github_issue_number if existing_gi else None
            issue_url = existing_gi.github_issue_url if existing_gi else None
            if queue_id:
                await db.delete(row)
        elif row.operation == SyncOperation.update and existing_gi:
            resp = await gh.patch(
                f"/repos/{repo_owner}/{repo_name}/issues/{existing_gi.github_issue_number}",
                json={
                    "title": snapshot["title"],
                    "body": snapshot["body"],
                    "labels": snapshot.get("github_labels", []),
                },
            )
            issue_number = existing_gi.github_issue_number
            issue_url = existing_gi.github_issue_url
            await db.delete(row)
        else:
            # create (or update fallback when no existing GithubItem)
            resp = await gh.post(
                f"/repos/{repo_owner}/{repo_name}/issues",
                json={
                    "title": snapshot["title"],
                    "body": snapshot["body"],
                    "labels": snapshot.get("github_labels", []),
                },
            )
            issue_number = resp["number"]
            issue_url = resp["html_url"]
            if existing_gi:
                existing_gi.github_issue_number = issue_number
                existing_gi.github_issue_url = issue_url
            else:
                gi = GithubItem(
                    item_type=row.item_type,
                    item_id=item_id,
                    github_issue_number=issue_number,
                    github_issue_url=issue_url,
                )
                db.add(gi)
            await db.delete(row)

        log = SyncLog(
            project_id=row.project_id,
            sync_queue_id=queue_id,
            item_type=row.item_type,
            item_id=item_id,
            operation=row.operation,
            status=SyncLogStatus.success,
            github_issue_number=issue_number,
            github_issue_url=issue_url,
        )
        db.add(log)
        return PushResultItem(
            item_type=row.item_type,
            item_id=item_id,
            github_issue_number=issue_number,
            github_issue_url=issue_url,
            error_code=None,
            error_message=None,
        )

    except (HTTPException, httpx.HTTPError) as exc:
        row.status = SyncQueueStatus.failed
        error_msg = str(exc.detail)[:1000] if isinstance(exc, HTTPException) else str(exc)[:1000]
        log = SyncLog(
            project_id=row.project_id,
            sync_queue_id=queue_id,
            item_type=row.item_type,
            item_id=item_id,
            operation=row.operation,
            status=SyncLogStatus.failed,
            error_code="GITHUB_API_ERROR",
            error_message=error_msg,
        )
        db.add(log)
        return PushResultItem(
            item_type=row.item_type,
            item_id=item_id,
            github_issue_number=None,
            github_issue_url=None,
            error_code="GITHUB_API_ERROR",
            error_message=error_msg,
        )


async def _get_parent_for_push(item_type: str, item_id: uuid.UUID, db: AsyncSession) -> uuid.UUID | None:
    """Return the parent's item_id UUID without loading the full ORM object."""
    if item_type == "feature":
        r = await db.execute(select(Feature.epic_id).where(Feature.id == item_id))
        return r.scalar_one_or_none()
    if item_type == "story":
        r = await db.execute(select(Story.feature_id).where(Story.id == item_id))
        return r.scalar_one_or_none()
    if item_type == "task":
        r = await db.execute(select(Task.story_id).where(Task.id == item_id))
        return r.scalar_one_or_none()
    return None


@router.post(
    "/projects/{project_id}/sync/push",
    response_model=ApiResponse[PushReport],
)
async def push_items(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    conn = await _require_connection(project_id, db)
    token = decrypt_token(conn.access_token)
    gh = GithubClient(token)

    rows_result = await db.execute(
        select(SyncQueue).where(
            SyncQueue.project_id == project_id,
            SyncQueue.status == SyncQueueStatus.pending,
        )
    )
    rows = list(rows_result.scalars().all())
    rows.sort(key=lambda r: _TYPE_ORDER[r.item_type.value])

    pushed: list[PushResultItem] = []
    failed: list[PushResultItem] = []

    for row in rows:
        result = await _push_one(row, gh, conn.repo_owner, conn.repo_name, db)
        if result.error_code:
            failed.append(result)
        else:
            pushed.append(result)

    await db.flush()
    return ok(PushReport(pushed=pushed, failed=failed))


# ── Logs ───────────────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/sync/logs",
    response_model=ApiResponse[list[SyncLogResponse]],
)
async def get_logs(
    project_id: uuid.UUID,
    item_id: uuid.UUID | None = Query(None),
    status: SyncLogStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)

    q = select(SyncLog).where(SyncLog.project_id == project_id)
    if item_id:
        q = q.where(SyncLog.item_id == item_id)
    if status:
        q = q.where(SyncLog.status == status)
    q = q.order_by(SyncLog.created_at.desc()).limit(limit).offset(offset)

    rows = await db.execute(q)
    return ok([SyncLogResponse.model_validate(r) for r in rows.scalars().all()])


# ── Repush ─────────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/sync/repush/{item_type}/{item_id}",
    response_model=ApiResponse[PushResultItem],
)
async def repush_item(
    project_id: uuid.UUID,
    item_type: ItemType,
    item_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    conn = await _require_connection(project_id, db)
    token = decrypt_token(conn.access_token)
    gh = GithubClient(token)

    item = await _load_item(item_type.value, item_id, project_id, db)
    snapshot = format_item(item, item_type.value)

    gi_result = await db.execute(
        select(GithubItem).where(GithubItem.item_type == item_type, GithubItem.item_id == item_id)
    )
    existing_gi = gi_result.scalar_one_or_none()
    operation = SyncOperation.update if existing_gi else SyncOperation.create

    # Build a transient queue row (not persisted) to reuse _push_one logic
    temp_row = SyncQueue(
        project_id=project_id,
        item_type=item_type,
        item_id=item_id,
        operation=operation,
        body_snapshot=snapshot,
        status=SyncQueueStatus.pending,
    )
    # Override sync_queue_id to null for repush logs
    result = await _push_repush(temp_row, gh, conn.repo_owner, conn.repo_name, db, existing_gi)
    await db.flush()
    return ok(result)


async def _push_repush(
    row: SyncQueue,
    gh: GithubClient,
    repo_owner: str,
    repo_name: str,
    db: AsyncSession,
    existing_gi: GithubItem | None,
) -> PushResultItem:
    snapshot = row.body_snapshot
    item_type = row.item_type.value
    item_id = row.item_id

    # Label validation — same enforcement as _push_one
    labels = snapshot.get("github_labels") or []
    missing_cats = [p for p in ("type:", "status:", "priority:") if not any(l.startswith(p) for l in labels)]
    if missing_cats:
        msg = f"Missing label categories: {', '.join(missing_cats)}"
        log = SyncLog(
            project_id=row.project_id,
            sync_queue_id=None,
            item_type=row.item_type,
            item_id=item_id,
            operation=row.operation,
            status=SyncLogStatus.failed,
            error_code="LABEL_INCOMPLETE",
            error_message=msg,
        )
        db.add(log)
        return PushResultItem(
            item_type=row.item_type,
            item_id=item_id,
            github_issue_number=None,
            github_issue_url=None,
            error_code="LABEL_INCOMPLETE",
            error_message=msg,
        )

    try:
        if existing_gi:
            resp = await gh.patch(
                f"/repos/{repo_owner}/{repo_name}/issues/{existing_gi.github_issue_number}",
                json={
                    "title": snapshot["title"],
                    "body": snapshot["body"],
                    "labels": snapshot.get("github_labels", []),
                },
            )
            issue_number = existing_gi.github_issue_number
            issue_url = existing_gi.github_issue_url
        else:
            resp = await gh.post(
                f"/repos/{repo_owner}/{repo_name}/issues",
                json={
                    "title": snapshot["title"],
                    "body": snapshot["body"],
                    "labels": snapshot.get("github_labels", []),
                },
            )
            issue_number = resp["number"]
            issue_url = resp["html_url"]
            gi = GithubItem(
                item_type=row.item_type,
                item_id=item_id,
                github_issue_number=issue_number,
                github_issue_url=issue_url,
            )
            db.add(gi)

        log = SyncLog(
            project_id=row.project_id,
            sync_queue_id=None,
            item_type=row.item_type,
            item_id=item_id,
            operation=row.operation,
            status=SyncLogStatus.success,
            github_issue_number=issue_number,
            github_issue_url=issue_url,
        )
        db.add(log)
        return PushResultItem(
            item_type=row.item_type,
            item_id=item_id,
            github_issue_number=issue_number,
            github_issue_url=issue_url,
            error_code=None,
            error_message=None,
        )
    except (HTTPException, httpx.HTTPError) as exc:
        error_msg = str(exc.detail)[:1000] if isinstance(exc, HTTPException) else str(exc)[:1000]
        log = SyncLog(
            project_id=row.project_id,
            sync_queue_id=None,
            item_type=row.item_type,
            item_id=item_id,
            operation=row.operation,
            status=SyncLogStatus.failed,
            error_code="GITHUB_API_ERROR",
            error_message=error_msg,
        )
        db.add(log)
        return PushResultItem(
            item_type=row.item_type,
            item_id=item_id,
            github_issue_number=None,
            github_issue_url=None,
            error_code="GITHUB_API_ERROR",
            error_message=error_msg,
        )
