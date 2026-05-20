import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt as _pyjwt
from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import decrypt_token  # legacy: OAuth-connected projects still use access_token
from app.core.github_client import (
    REQFLOW_LABELS,
    SPRINT_MILESTONE_TITLE,
    GithubClient,
)
from app.models.github_connection import GithubConnection
from app.models.requirements import AcceptanceCriteria, Epic, Feature, ItemType, Story, Task
from app.models.project import Project
from app.models.sync import GithubItem

from app.schemas.github import (
    BootstrapReport,
    BootstrapResourceResult,
    GithubConnectionStatusResponse,
    GithubIssuePreview,
    GithubSelectRepoRequest,
    ImportConfirmRequest,
    ImportPreviewResponse,
    ImportedItem,
)

_logger = logging.getLogger(__name__)
_TYPE_ORDER = {"epic": 0, "feature": 1, "story": 2, "task": 3}
_GITHUB_APP_INSTALLATIONS_URL = "https://api.github.com/app/installations"
_CLOSE_MESSAGES: dict[str, str] = {
    "done": "Completed. Acceptance criteria verified.",
    "rejected": "Rejected: out of scope.",
    "duplicate": "Duplicate. Closing this one.",
    "wont_fix": "Won't implement.",
    "deferred": "Deferred to a later sprint.",
}
class GithubService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Connection management ---

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
                    f"{_GITHUB_APP_INSTALLATIONS_URL}/{installation_id}/access_tokens",
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
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Không thể tạo GitHub installation token")
            except httpx.RequestError:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Không thể kết nối GitHub")

    async def _require_connection(self, project_id: uuid.UUID) -> GithubConnection:
        result = await self.db.execute(
            select(GithubConnection).where(GithubConnection.project_id == project_id)
        )
        conn = result.scalar_one_or_none()
        if not conn or (not conn.installation_id and not conn.access_token):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Chưa kết nối GitHub — vui lòng kết nối lại",
            )
        return conn

    async def _get_client(self, conn: GithubConnection) -> GithubClient:
        if conn.installation_id:
            token = await self._generate_installation_token(conn.installation_id)
        else:
            token = decrypt_token(conn.access_token) if conn.access_token else None
        if not token:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Token GitHub không hợp lệ — vui lòng kết nối lại",
            )
        return GithubClient(token)

    async def _handle_token_revoked(self, conn: GithubConnection, exc: HTTPException) -> None:
        if exc.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            conn.access_token = None
            conn.installation_id = None
            conn.bootstrap_status = "failed"
            await self.db.flush()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="GitHub token đã bị thu hồi — vui lòng kết nối lại",
            )
        raise exc

    async def complete_app_install(
        self, installation_id: str, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> GithubConnection:
        stmt = (
            pg_insert(GithubConnection)
            .values(
                project_id=project_id,
                installation_id=installation_id,
                access_token=None,
                connected_by_user_id=user_id,
                repo_owner="",
                repo_name="",
                bootstrap_status="not_started",
                sync_mode="manual",
            )
            .on_conflict_do_update(
                index_elements=["project_id"],
                set_={
                    "installation_id": installation_id,
                    "access_token": None,
                    "connected_by_user_id": user_id,
                    "bootstrap_status": "not_started",
                },
            )
        )
        await self.db.execute(stmt)
        await self.db.flush()
        result = await self.db.execute(
            select(GithubConnection).where(GithubConnection.project_id == project_id)
        )
        return result.scalar_one()

    async def select_repo(self, project_id: uuid.UUID, body: GithubSelectRepoRequest) -> GithubConnection:
        conn = await self._require_connection(project_id)
        gh = await self._get_client(conn)
        try:
            await gh.get(f"/repos/{body.repo_owner}/{body.repo_name}")
        except HTTPException as exc:
            if exc.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
                await self._handle_token_revoked(conn, exc)
            raise HTTPException(exc.status_code, detail=f"Không thể truy cập repo: {exc.detail}")
        conn.repo_owner = body.repo_owner
        conn.repo_name = body.repo_name
        await self.db.flush()
        return conn

    async def list_repos(self, project_id: uuid.UUID) -> list[dict]:
        conn = await self._require_connection(project_id)
        gh = await self._get_client(conn)
        try:
            if conn.installation_id:
                data = await gh.get("/installation/repositories", params={"per_page": 100})
                repos = data["repositories"] if isinstance(data, dict) else data
            else:
                repos = await gh.get("/user/repos", params={"affiliation": "owner,collaborator", "per_page": 100})
        except HTTPException as exc:
            await self._handle_token_revoked(conn, exc)
            raise
        return [{"full_name": r["full_name"], "private": r["private"], "html_url": r["html_url"]} for r in repos]

    async def get_status(self, project_id: uuid.UUID) -> GithubConnectionStatusResponse:
        result = await self.db.execute(
            select(GithubConnection).where(GithubConnection.project_id == project_id)
        )
        conn = result.scalar_one_or_none()
        if not conn:
            return GithubConnectionStatusResponse(connected=False, bootstrap_status="not_started")
        return GithubConnectionStatusResponse(
            connected=bool(conn.installation_id or conn.access_token),
            repo_owner=conn.repo_owner or None,
            repo_name=conn.repo_name or None,
            bootstrap_status=conn.bootstrap_status,
            sync_mode=conn.sync_mode,
        )

    async def bootstrap(self, project_id: uuid.UUID) -> BootstrapReport:
        conn = await self._require_connection(project_id)
        conn.bootstrap_status = "in_progress"
        await self.db.flush()

        gh = await self._get_client(conn)
        try:
            label_results = await self._bootstrap_labels(gh, conn.repo_owner, conn.repo_name)
            milestone_result = await self._bootstrap_milestone(gh, conn.repo_owner, conn.repo_name)
        except HTTPException as exc:
            await self._handle_token_revoked(conn, exc)
            raise

        all_ok = (
            all(r.status != "failed" for r in label_results)
            and milestone_result.status != "failed"
        )
        conn.bootstrap_status = "completed" if all_ok else "failed"
        await self.db.flush()

        return BootstrapReport(labels=label_results, milestone=milestone_result)

    async def _bootstrap_labels(
        self, gh: GithubClient, owner: str, repo: str
    ) -> list[BootstrapResourceResult]:
        try:
            existing = await gh.get(f"/repos/{owner}/{repo}/labels", params={"per_page": 100})
            existing_names = {lbl["name"] for lbl in existing}
        except HTTPException:
            existing_names = set()

        results: list[BootstrapResourceResult] = []
        for lbl in REQFLOW_LABELS:
            if lbl["name"] in existing_names:
                results.append(BootstrapResourceResult(name=lbl["name"], status="already_present"))
                continue
            try:
                await gh.post(f"/repos/{owner}/{repo}/labels", json=lbl)
                results.append(BootstrapResourceResult(name=lbl["name"], status="created"))
            except HTTPException as exc:
                results.append(BootstrapResourceResult(name=lbl["name"], status="failed", detail=exc.detail))
        return results

    async def _bootstrap_milestone(
        self, gh: GithubClient, owner: str, repo: str
    ) -> BootstrapResourceResult:
        try:
            milestones = await gh.get(f"/repos/{owner}/{repo}/milestones", params={"state": "open"})
            if any(m["title"] == SPRINT_MILESTONE_TITLE for m in milestones):
                return BootstrapResourceResult(name=SPRINT_MILESTONE_TITLE, status="already_present")
            due = (datetime.now(timezone.utc) + timedelta(weeks=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
            await gh.post(f"/repos/{owner}/{repo}/milestones", json={
                "title": SPRINT_MILESTONE_TITLE,
                "due_on": due,
                "description": "ReqFlow Sprint 1",
            })
            return BootstrapResourceResult(name=SPRINT_MILESTONE_TITLE, status="created")
        except HTTPException as exc:
            return BootstrapResourceResult(name=SPRINT_MILESTONE_TITLE, status="failed", detail=exc.detail)

    async def import_preview(self, project_id: uuid.UUID) -> ImportPreviewResponse:
        conn = await self._require_connection(project_id)
        gh = await self._get_client(conn)
        try:
            issues = await gh.get(
                f"/repos/{conn.repo_owner}/{conn.repo_name}/issues",
                params={"state": "open", "per_page": 100},
            )
        except HTTPException as exc:
            await self._handle_token_revoked(conn, exc)
            raise
        preview = ImportPreviewResponse(truncated=len(issues) >= 100)
        for issue in issues:
            if issue.get("pull_request"):
                continue
            label_names = [lbl["name"] for lbl in issue.get("labels", [])]
            item = GithubIssuePreview(
                github_issue_number=issue["number"],
                title=issue["title"],
                body=issue.get("body"),
                labels=label_names,
            )
            if "type:epic" in label_names:
                preview.epics.append(item)
            elif "type:feature" in label_names:
                preview.features.append(item)
            elif "type:story" in label_names:
                preview.stories.append(item)
            elif "type:task" in label_names:
                preview.tasks.append(item)
            else:
                preview.unclassified.append(item)
        return preview

    async def post_close_comment(
        self,
        project_id: uuid.UUID,
        item_type: ItemType,
        item_id: uuid.UUID,
        reason: str,
        comment: str,
    ) -> None:
        try:
            result = await self.db.execute(
                select(GithubItem).where(
                    GithubItem.item_type == item_type,
                    GithubItem.item_id == item_id,
                )
            )
            gi = result.scalar_one_or_none()
            if not gi:
                return

            conn = await self._require_connection(project_id)
            gh = await self._get_client(conn)

            text = _CLOSE_MESSAGES.get(reason, "Closed.")
            if comment.strip():
                text = f"{text} — {comment}"

            await gh.post(
                f"/repos/{conn.repo_owner}/{conn.repo_name}/issues/{gi.github_issue_number}/comments",
                json={"body": text},
            )
        except HTTPException:
            return
        except Exception:
            _logger.warning(
                "Failed to post close comment for %s %s", item_type, item_id, exc_info=True
            )

    async def import_confirm(
        self, project_id: uuid.UUID, body: ImportConfirmRequest
    ) -> list[ImportedItem]:
        conn = await self._require_connection(project_id)
        gh = await self._get_client(conn)

        try:
            raw_issues = await gh.get(
                f"/repos/{conn.repo_owner}/{conn.repo_name}/issues",
                params={"state": "all", "per_page": 100},
            )
        except HTTPException as exc:
            await self._handle_token_revoked(conn, exc)
            raise

        issue_titles: dict[int, str] = {
            i["number"]: i["title"] for i in raw_issues if not i.get("pull_request")
        }

        ordered = sorted(body.mappings, key=lambda m: _TYPE_ORDER[m.item_type])
        created_entities: dict[int, Epic | Feature | Story | Task] = {}
        results: list[ImportedItem] = []

        for mapping in ordered:
            title = mapping.title or issue_titles.get(
                mapping.github_issue_number, f"Issue #{mapping.github_issue_number}"
            )
            parent_num = mapping.parent_github_issue_number
            parent = created_entities.get(parent_num) if parent_num else None

            if mapping.item_type == "epic":
                await self.db.execute(
                    select(Project).where(Project.id == project_id).with_for_update()
                )
                max_n = await self.db.scalar(
                    select(func.max(cast(func.substr(Epic.prefix, 2), Integer)))
                    .where(Epic.project_id == project_id)
                )
                prefix = f"E{(max_n or 0) + 1}"
                entity: Any = Epic(project_id=project_id, prefix=prefix, title=title)

            elif mapping.item_type == "feature":
                if not isinstance(parent, Epic):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Issue #{mapping.github_issue_number}: issue cha #{parent_num} không phải là epic",
                    )
                await self.db.execute(
                    select(Epic).where(Epic.id == parent.id).with_for_update()
                )
                offset = len(parent.prefix) + 3
                max_n = await self.db.scalar(
                    select(func.max(cast(func.substr(Feature.prefix, offset), Integer)))
                    .where(Feature.epic_id == parent.id)
                )
                prefix = f"{parent.prefix}.F{(max_n or 0) + 1}"
                entity = Feature(epic_id=parent.id, prefix=prefix, title=title)

            elif mapping.item_type == "story":
                if not isinstance(parent, Feature):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Issue #{mapping.github_issue_number}: issue cha #{parent_num} không phải là feature",
                    )
                await self.db.execute(
                    select(Feature).where(Feature.id == parent.id).with_for_update()
                )
                offset = len(parent.prefix) + 3
                max_n = await self.db.scalar(
                    select(func.max(cast(func.substr(Story.prefix, offset), Integer)))
                    .where(Story.feature_id == parent.id)
                )
                prefix = f"{parent.prefix}.S{(max_n or 0) + 1}"
                entity = Story(feature_id=parent.id, prefix=prefix, title=title)

            else:  # task
                if not isinstance(parent, Story):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Issue #{mapping.github_issue_number}: issue cha #{parent_num} không phải là story",
                    )
                await self.db.execute(
                    select(Story).where(Story.id == parent.id).with_for_update()
                )
                offset = len(parent.prefix) + 3
                max_n = await self.db.scalar(
                    select(func.max(cast(func.substr(Task.prefix, offset), Integer)))
                    .where(Task.story_id == parent.id)
                )
                prefix = f"{parent.prefix}.T{(max_n or 0) + 1}"
                entity = Task(story_id=parent.id, prefix=prefix, title=title)

            self.db.add(entity)
            await self.db.flush()
            created_entities[mapping.github_issue_number] = entity
            results.append(ImportedItem(
                github_issue_number=mapping.github_issue_number,
                item_type=mapping.item_type,
                prefix=entity.prefix,
                title=title,
                db_id=entity.id,
            ))

        return results
