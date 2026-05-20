import time
import uuid
from typing import Any

import httpx
import jwt as _pyjwt
from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.crypto import decrypt_token
from app.core.github_client import GithubClient
from app.core.sync_formatter import format_item
from app.models.github_connection import GithubConnection
from app.models.requirements import Epic, Feature, ItemType, Story, Task
from app.models.sync import (
    GithubItem,
    SyncLog,
    SyncLogStatus,
    SyncOperation,
    SyncQueue,
    SyncQueueStatus,
)
from app.schemas.sync import PushReport, PushResultItem, StageRequest, SyncLogResponse, SyncQueueResponse

_TYPE_ORDER = {"epic": 0, "feature": 1, "story": 2, "task": 3}


class SyncService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _make_app_jwt(self) -> str:
        now = int(time.time())
        private_key = settings.github_app_private_key.replace("\\n", "\n")
        return _pyjwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id},
            private_key,
            algorithm="RS256",
        )

    async def _generate_installation_token(self, installation_id: str) -> str:
        app_jwt = self._make_app_jwt()
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                    headers={
                        "Authorization": f"Bearer {app_jwt}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                return resp.json()["token"]
            except httpx.HTTPStatusError:
                raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, detail="Không thể tạo GitHub installation token")
            except httpx.RequestError:
                raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, detail="Không thể kết nối GitHub")

    async def _require_connection(self, project_id: uuid.UUID) -> GithubConnection:
        result = await self.db.execute(
            select(GithubConnection).where(GithubConnection.project_id == project_id)
        )
        conn = result.scalar_one_or_none()
        if not conn or (not conn.installation_id and not conn.access_token):
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                detail="Chưa kết nối GitHub — vui lòng kết nối dự án trước",
            )
        return conn

    async def _get_client(self, conn: GithubConnection) -> GithubClient:
        if conn.installation_id:
            token = await self._generate_installation_token(conn.installation_id)
        else:
            token = decrypt_token(conn.access_token) if conn.access_token else None
        if not token:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                detail="Token GitHub không hợp lệ — vui lòng kết nối lại",
            )
        return GithubClient(token)

    async def _load_item(self, item_type: str, item_id: uuid.UUID, project_id: uuid.UUID) -> Any:
        if item_type == "epic":
            q = select(Epic).where(Epic.id == item_id, Epic.project_id == project_id)
        elif item_type == "feature":
            q = (
                select(Feature)
                .options(selectinload(Feature.nfrs))
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
            raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail=f"Loại item không hợp lệ: {item_type}")

        result = await self.db.execute(q)
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(
                http_status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy {item_type} {item_id} trong dự án",
            )
        return item

    def _parent_type(self, item_type: str) -> str | None:
        return {"feature": "epic", "story": "feature", "task": "story"}.get(item_type)

    async def _get_parent_for_push(self, item_type: str, item_id: uuid.UUID) -> uuid.UUID | None:
        if item_type == "feature":
            r = await self.db.execute(select(Feature.epic_id).where(Feature.id == item_id))
            return r.scalar_one_or_none()
        if item_type == "story":
            r = await self.db.execute(select(Story.feature_id).where(Story.id == item_id))
            return r.scalar_one_or_none()
        if item_type == "task":
            r = await self.db.execute(select(Task.story_id).where(Task.id == item_id))
            return r.scalar_one_or_none()
        return None

    async def stage_items(self, project_id: uuid.UUID, body: StageRequest) -> list[SyncQueueResponse]:
        for req_item in body.items:
            item = await self._load_item(req_item.item_type.value, req_item.item_id, project_id)
            snapshot = format_item(item, req_item.item_type.value)

            gi_result = await self.db.execute(
                select(GithubItem).where(
                    GithubItem.item_type == req_item.item_type,
                    GithubItem.item_id == req_item.item_id,
                )
            )
            operation = SyncOperation.update if gi_result.scalar_one_or_none() else SyncOperation.create

            existing = await self.db.execute(
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
                self.db.add(queue_row)

        await self.db.flush()

        rows = await self.db.execute(
            select(SyncQueue).where(SyncQueue.project_id == project_id).order_by(SyncQueue.created_at)
        )
        return [SyncQueueResponse.model_validate(r) for r in rows.scalars().all()]

    async def get_pending(self, project_id: uuid.UUID) -> list[SyncQueueResponse]:
        rows = await self.db.execute(
            select(SyncQueue)
            .where(SyncQueue.project_id == project_id)
            .order_by(SyncQueue.created_at)
        )
        return [SyncQueueResponse.model_validate(r) for r in rows.scalars().all()]

    async def unstage_item(self, project_id: uuid.UUID, queue_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(SyncQueue).where(SyncQueue.id == queue_id, SyncQueue.project_id == project_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail="Không tìm thấy mục trong hàng đợi")
        await self.db.delete(row)
        await self.db.flush()

    async def push_items(self, project_id: uuid.UUID) -> PushReport:
        conn = await self._require_connection(project_id)
        gh = await self._get_client(conn)

        rows_result = await self.db.execute(
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
            result = await self._push_one(row, gh, conn.repo_owner, conn.repo_name)
            if result.error_code:
                failed.append(result)
            else:
                pushed.append(result)

        await self.db.flush()
        return PushReport(pushed=pushed, failed=failed)

    async def repush_item(
        self, project_id: uuid.UUID, item_type: ItemType, item_id: uuid.UUID
    ) -> PushResultItem:
        conn = await self._require_connection(project_id)
        gh = await self._get_client(conn)

        item = await self._load_item(item_type.value, item_id, project_id)
        snapshot = format_item(item, item_type.value)

        gi_result = await self.db.execute(
            select(GithubItem).where(GithubItem.item_type == item_type, GithubItem.item_id == item_id)
        )
        existing_gi = gi_result.scalar_one_or_none()
        operation = SyncOperation.update if existing_gi else SyncOperation.create

        temp_row = SyncQueue(
            project_id=project_id,
            item_type=item_type,
            item_id=item_id,
            operation=operation,
            body_snapshot=snapshot,
            status=SyncQueueStatus.pending,
        )
        result = await self._push_repush(temp_row, gh, conn.repo_owner, conn.repo_name, existing_gi)
        await self.db.flush()
        return result

    async def get_logs(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID | None,
        status: SyncLogStatus | None,
        limit: int,
        offset: int,
    ) -> list[SyncLogResponse]:
        q = select(SyncLog).where(SyncLog.project_id == project_id)
        if item_id:
            q = q.where(SyncLog.item_id == item_id)
        if status:
            q = q.where(SyncLog.status == status)
        q = q.order_by(SyncLog.created_at.desc()).limit(limit).offset(offset)
        rows = await self.db.execute(q)
        return [SyncLogResponse.model_validate(r) for r in rows.scalars().all()]

    async def _push_one(
        self,
        row: SyncQueue,
        gh: GithubClient,
        repo_owner: str,
        repo_name: str,
    ) -> PushResultItem:
        snapshot = row.body_snapshot
        item_type = row.item_type.value
        item_id = row.item_id

        labels = snapshot.get("github_labels") or []
        missing_cats = [p for p in ("type:", "status:", "priority:") if not any(l.startswith(p) for l in labels)]
        if missing_cats:
            row.status = SyncQueueStatus.failed
            msg = f"Thiếu nhãn thuộc nhóm: {', '.join(missing_cats)}"
            self.db.add(SyncLog(
                project_id=row.project_id,
                sync_queue_id=row.id,
                item_type=row.item_type,
                item_id=item_id,
                operation=row.operation,
                status=SyncLogStatus.failed,
                error_code="LABEL_INCOMPLETE",
                error_message=msg,
            ))
            return PushResultItem(
                item_type=row.item_type,
                item_id=item_id,
                github_issue_number=None,
                github_issue_url=None,
                error_code="LABEL_INCOMPLETE",
                error_message=msg,
            )

        p_type = self._parent_type(item_type)
        if p_type:
            parent_id = await self._get_parent_for_push(item_type, item_id)
            if parent_id is not None:
                gi = await self.db.execute(
                    select(GithubItem).where(
                        GithubItem.item_type == ItemType(p_type),
                        GithubItem.item_id == parent_id,
                    )
                )
                if not gi.scalar_one_or_none():
                    row.status = SyncQueueStatus.failed
                    msg = f"{p_type} cha chưa có issue trên GitHub — hãy push {p_type} cha trước"
                    self.db.add(SyncLog(
                        project_id=row.project_id,
                        sync_queue_id=row.id,
                        item_type=row.item_type,
                        item_id=item_id,
                        operation=row.operation,
                        status=SyncLogStatus.failed,
                        error_code="MISSING_PARENT_ISSUE",
                        error_message=msg,
                    ))
                    return PushResultItem(
                        item_type=row.item_type,
                        item_id=item_id,
                        github_issue_number=None,
                        github_issue_url=None,
                        error_code="MISSING_PARENT_ISSUE",
                        error_message=msg,
                    )

        gi_result = await self.db.execute(
            select(GithubItem).where(GithubItem.item_type == row.item_type, GithubItem.item_id == item_id)
        )
        existing_gi = gi_result.scalar_one_or_none()
        queue_id = row.id

        try:
            if row.operation == SyncOperation.close:
                if existing_gi:
                    await gh.patch(
                        f"/repos/{repo_owner}/{repo_name}/issues/{existing_gi.github_issue_number}",
                        json={"state": "closed"},
                    )
                issue_number = existing_gi.github_issue_number if existing_gi else None
                issue_url = existing_gi.github_issue_url if existing_gi else None
            elif row.operation == SyncOperation.update and existing_gi:
                await gh.patch(
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
                if existing_gi:
                    existing_gi.github_issue_number = issue_number
                    existing_gi.github_issue_url = issue_url
                else:
                    self.db.add(GithubItem(
                        item_type=row.item_type,
                        item_id=item_id,
                        github_issue_number=issue_number,
                        github_issue_url=issue_url,
                    ))

            # Stage log before deleting queue row — ensures FK is resolved before DELETE is emitted
            self.db.add(SyncLog(
                project_id=row.project_id,
                sync_queue_id=queue_id,
                item_type=row.item_type,
                item_id=item_id,
                operation=row.operation,
                status=SyncLogStatus.success,
                github_issue_number=issue_number,
                github_issue_url=issue_url,
            ))
            await self.db.delete(row)
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
            self.db.add(SyncLog(
                project_id=row.project_id,
                sync_queue_id=queue_id,
                item_type=row.item_type,
                item_id=item_id,
                operation=row.operation,
                status=SyncLogStatus.failed,
                error_code="GITHUB_API_ERROR",
                error_message=error_msg,
            ))
            return PushResultItem(
                item_type=row.item_type,
                item_id=item_id,
                github_issue_number=None,
                github_issue_url=None,
                error_code="GITHUB_API_ERROR",
                error_message=error_msg,
            )

    async def _push_repush(
        self,
        row: SyncQueue,
        gh: GithubClient,
        repo_owner: str,
        repo_name: str,
        existing_gi: GithubItem | None,
    ) -> PushResultItem:
        snapshot = row.body_snapshot
        item_type = row.item_type.value
        item_id = row.item_id

        labels = snapshot.get("github_labels") or []
        missing_cats = [p for p in ("type:", "status:", "priority:") if not any(l.startswith(p) for l in labels)]
        if missing_cats:
            msg = f"Thiếu nhãn thuộc nhóm: {', '.join(missing_cats)}"
            self.db.add(SyncLog(
                project_id=row.project_id,
                sync_queue_id=None,
                item_type=row.item_type,
                item_id=item_id,
                operation=row.operation,
                status=SyncLogStatus.failed,
                error_code="LABEL_INCOMPLETE",
                error_message=msg,
            ))
            return PushResultItem(
                item_type=row.item_type,
                item_id=item_id,
                github_issue_number=None,
                github_issue_url=None,
                error_code="LABEL_INCOMPLETE",
                error_message=msg,
            )

        p_type = self._parent_type(item_type)
        if p_type:
            parent_id = await self._get_parent_for_push(item_type, item_id)
            if parent_id is not None:
                gi = await self.db.execute(
                    select(GithubItem).where(
                        GithubItem.item_type == ItemType(p_type),
                        GithubItem.item_id == parent_id,
                    )
                )
                if not gi.scalar_one_or_none():
                    msg = f"{p_type} cha chưa có issue trên GitHub — hãy push {p_type} cha trước"
                    self.db.add(SyncLog(
                        project_id=row.project_id,
                        sync_queue_id=None,
                        item_type=row.item_type,
                        item_id=item_id,
                        operation=row.operation,
                        status=SyncLogStatus.failed,
                        error_code="MISSING_PARENT_ISSUE",
                        error_message=msg,
                    ))
                    return PushResultItem(
                        item_type=row.item_type,
                        item_id=item_id,
                        github_issue_number=None,
                        github_issue_url=None,
                        error_code="MISSING_PARENT_ISSUE",
                        error_message=msg,
                    )

        try:
            if row.operation == SyncOperation.close:
                if existing_gi:
                    await gh.patch(
                        f"/repos/{repo_owner}/{repo_name}/issues/{existing_gi.github_issue_number}",
                        json={"state": "closed"},
                    )
                issue_number = existing_gi.github_issue_number if existing_gi else None
                issue_url = existing_gi.github_issue_url if existing_gi else None
            elif existing_gi:
                await gh.patch(
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
                self.db.add(GithubItem(
                    item_type=row.item_type,
                    item_id=item_id,
                    github_issue_number=issue_number,
                    github_issue_url=issue_url,
                ))

            self.db.add(SyncLog(
                project_id=row.project_id,
                sync_queue_id=None,
                item_type=row.item_type,
                item_id=item_id,
                operation=row.operation,
                status=SyncLogStatus.success,
                github_issue_number=issue_number,
                github_issue_url=issue_url,
            ))
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
            self.db.add(SyncLog(
                project_id=row.project_id,
                sync_queue_id=None,
                item_type=row.item_type,
                item_id=item_id,
                operation=row.operation,
                status=SyncLogStatus.failed,
                error_code="GITHUB_API_ERROR",
                error_message=error_msg,
            ))
            return PushResultItem(
                item_type=row.item_type,
                item_id=item_id,
                github_issue_number=None,
                github_issue_url=None,
                error_code="GITHUB_API_ERROR",
                error_message=error_msg,
            )
