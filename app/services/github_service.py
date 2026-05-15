import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import decrypt_token, encrypt_token
from app.core.github_client import (
    BOARD_COLUMNS,
    BOARD_TITLE,
    REQFLOW_LABELS,
    SPRINT_MILESTONE_TITLE,
    GithubClient,
)
from app.models.github_connection import GithubConnection
from app.models.requirements import AcceptanceCriteria, Epic, Feature, Story, Task
from app.models.project import Project
from app.schemas.github import (
    BootstrapReport,
    BootstrapResourceResult,
    GithubConnectRequest,
    GithubConnectionStatusResponse,
    GithubIssuePreview,
    GithubSelectRepoRequest,
    ImportConfirmRequest,
    ImportPreviewResponse,
    ImportedItem,
)

_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_TYPE_ORDER = {"epic": 0, "feature": 1, "story": 2, "task": 3}


class GithubService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _require_connection(self, project_id: uuid.UUID) -> GithubConnection:
        result = await self.db.execute(
            select(GithubConnection).where(GithubConnection.project_id == project_id)
        )
        conn = result.scalar_one_or_none()
        if not conn or not conn.access_token:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="No GitHub connection — connect the project first",
            )
        return conn

    def _get_client(self, conn: GithubConnection) -> GithubClient:
        token = decrypt_token(conn.access_token)
        if not token:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Stored GitHub token could not be decrypted",
            )
        return GithubClient(token)

    async def complete_oauth_connect(self, code: str, project_id: uuid.UUID) -> None:
        """Exchange OAuth code for token and upsert the GithubConnection record."""
        async with httpx.AsyncClient() as client:
            try:
                token_resp = await client.post(
                    _GITHUB_TOKEN_URL,
                    data={
                        "client_id": settings.github_client_id,
                        "client_secret": settings.github_client_secret,
                        "code": code,
                        "redirect_uri": settings.github_repo_connect_redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                    timeout=10,
                )
                token_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    detail=f"GitHub token exchange failed: {exc.response.status_code}",
                )
            except httpx.RequestError:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="GitHub unreachable")

        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="GitHub did not return an access token")

        encrypted = encrypt_token(access_token)
        result = await self.db.execute(
            select(GithubConnection).where(GithubConnection.project_id == project_id)
        )
        conn = result.scalar_one_or_none()
        if conn:
            conn.access_token = encrypted
            conn.bootstrap_status = "not_started"
        else:
            conn = GithubConnection(
                project_id=project_id,
                repo_owner="",
                repo_name="",
                access_token=encrypted,
                bootstrap_status="not_started",
            )
            self.db.add(conn)
        await self.db.flush()

    async def connect_pat(self, project_id: uuid.UUID, body: GithubConnectRequest) -> GithubConnection:
        gh = GithubClient(body.access_token)
        try:
            await gh.get(f"/repos/{body.repo_owner}/{body.repo_name}")
        except HTTPException as exc:
            raise HTTPException(exc.status_code, detail=f"Cannot access repo: {exc.detail}")

        encrypted = encrypt_token(body.access_token)
        result = await self.db.execute(
            select(GithubConnection).where(GithubConnection.project_id == project_id)
        )
        conn = result.scalar_one_or_none()
        if conn:
            conn.repo_owner = body.repo_owner
            conn.repo_name = body.repo_name
            conn.access_token = encrypted
            conn.bootstrap_status = "not_started"
        else:
            conn = GithubConnection(
                project_id=project_id,
                repo_owner=body.repo_owner,
                repo_name=body.repo_name,
                access_token=encrypted,
                bootstrap_status="not_started",
            )
            self.db.add(conn)
        await self.db.flush()
        return conn

    async def select_repo(self, project_id: uuid.UUID, body: GithubSelectRepoRequest) -> GithubConnection:
        conn = await self._require_connection(project_id)
        gh = self._get_client(conn)
        try:
            await gh.get(f"/repos/{body.repo_owner}/{body.repo_name}")
        except HTTPException as exc:
            raise HTTPException(exc.status_code, detail=f"Cannot access repo: {exc.detail}")
        conn.repo_owner = body.repo_owner
        conn.repo_name = body.repo_name
        await self.db.flush()
        return conn

    async def list_repos(self, project_id: uuid.UUID) -> list[dict]:
        conn = await self._require_connection(project_id)
        gh = self._get_client(conn)
        repos = await gh.get("/user/repos", params={"sort": "updated", "per_page": 50})
        return [{"full_name": r["full_name"], "private": r["private"], "html_url": r["html_url"]} for r in repos]

    async def get_status(self, project_id: uuid.UUID) -> GithubConnectionStatusResponse:
        result = await self.db.execute(
            select(GithubConnection).where(GithubConnection.project_id == project_id)
        )
        conn = result.scalar_one_or_none()
        if not conn:
            return GithubConnectionStatusResponse(connected=False, bootstrap_status="not_started")
        return GithubConnectionStatusResponse(
            connected=bool(conn.access_token),
            repo_owner=conn.repo_owner or None,
            repo_name=conn.repo_name or None,
            bootstrap_status=conn.bootstrap_status,
            sync_mode=conn.sync_mode,
        )

    async def bootstrap(self, project_id: uuid.UUID) -> BootstrapReport:
        conn = await self._require_connection(project_id)
        gh = self._get_client(conn)

        conn.bootstrap_status = "in_progress"
        await self.db.flush()

        label_results = await self._bootstrap_labels(gh, conn.repo_owner, conn.repo_name)
        milestone_result = await self._bootstrap_milestone(gh, conn.repo_owner, conn.repo_name)
        board_result = await self._bootstrap_board(gh, conn.repo_owner, conn.repo_name)

        all_ok = (
            all(r.status != "failed" for r in label_results)
            and milestone_result.status != "failed"
            and board_result.status != "failed"
        )
        conn.bootstrap_status = "completed" if all_ok else "failed"
        await self.db.flush()

        return BootstrapReport(labels=label_results, milestone=milestone_result, board=board_result)

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

    async def _bootstrap_board(
        self, gh: GithubClient, owner: str, repo: str
    ) -> BootstrapResourceResult:
        try:
            repo_data = await gh.graphql(
                """
                query($owner: String!, $name: String!) {
                  repository(owner: $owner, name: $name) {
                    id
                    owner { id }
                  }
                }
                """,
                {"owner": owner, "name": repo},
            )
            owner_node_id = repo_data["repository"]["owner"]["id"]

            project_data = await gh.graphql(
                """
                mutation($ownerId: ID!, $title: String!) {
                  createProjectV2(input: {ownerId: $ownerId, title: $title}) {
                    projectV2 { id url }
                  }
                }
                """,
                {"ownerId": owner_node_id, "title": BOARD_TITLE},
            )
            project_id_node = project_data["createProjectV2"]["projectV2"]["id"]
            board_url = project_data["createProjectV2"]["projectV2"]["url"]

            fields_data = await gh.graphql(
                """
                query($id: ID!) {
                  node(id: $id) {
                    ... on ProjectV2 {
                      fields(first: 20) {
                        nodes {
                          ... on ProjectV2SingleSelectField {
                            id name
                            options { id name }
                          }
                        }
                      }
                    }
                  }
                }
                """,
                {"id": project_id_node},
            )
            status_field = next(
                (f for f in fields_data["node"]["fields"]["nodes"] if f.get("name") == "Status"),
                None,
            )
            if status_field:
                column_colors = ["GRAY", "BLUE", "YELLOW", "ORANGE", "GREEN"]
                options = [
                    {"name": col, "color": column_colors[i % len(column_colors)], "description": ""}
                    for i, col in enumerate(BOARD_COLUMNS)
                ]
                await gh.graphql(
                    """
                    mutation($input: UpdateProjectV2FieldInput!) {
                      updateProjectV2Field(input: $input) {
                        projectV2Field {
                          ... on ProjectV2SingleSelectField { id name }
                        }
                      }
                    }
                    """,
                    {"input": {
                        "fieldId": status_field["id"],
                        "projectId": project_id_node,
                        "singleSelectField": {"options": options},
                    }},
                )

            return BootstrapResourceResult(name=BOARD_TITLE, status="created", detail=board_url)
        except HTTPException as exc:
            return BootstrapResourceResult(name=BOARD_TITLE, status="failed", detail=exc.detail)
        except Exception as exc:
            return BootstrapResourceResult(name=BOARD_TITLE, status="failed", detail=str(exc))

    async def import_preview(self, project_id: uuid.UUID) -> ImportPreviewResponse:
        conn = await self._require_connection(project_id)
        gh = self._get_client(conn)
        issues = await gh.get(
            f"/repos/{conn.repo_owner}/{conn.repo_name}/issues",
            params={"state": "open", "per_page": 100},
        )
        preview = ImportPreviewResponse()
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

    async def import_confirm(
        self, project_id: uuid.UUID, body: ImportConfirmRequest
    ) -> list[ImportedItem]:
        conn = await self._require_connection(project_id)
        gh = self._get_client(conn)

        raw_issues = await gh.get(
            f"/repos/{conn.repo_owner}/{conn.repo_name}/issues",
            params={"state": "all", "per_page": 100},
        )
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
                count = await self.db.scalar(
                    select(func.count(Epic.id)).where(Epic.project_id == project_id)
                )
                prefix = f"E{(count or 0) + 1}"
                entity: Any = Epic(project_id=project_id, prefix=prefix, title=title)

            elif mapping.item_type == "feature":
                if not isinstance(parent, Epic):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Issue #{mapping.github_issue_number}: parent issue #{parent_num} is not an epic",
                    )
                await self.db.execute(
                    select(Epic).where(Epic.id == parent.id).with_for_update()
                )
                count = await self.db.scalar(
                    select(func.count(Feature.id)).where(Feature.epic_id == parent.id)
                )
                prefix = f"{parent.prefix}.F{(count or 0) + 1}"
                entity = Feature(epic_id=parent.id, prefix=prefix, title=title)

            elif mapping.item_type == "story":
                if not isinstance(parent, Feature):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Issue #{mapping.github_issue_number}: parent issue #{parent_num} is not a feature",
                    )
                await self.db.execute(
                    select(Feature).where(Feature.id == parent.id).with_for_update()
                )
                count = await self.db.scalar(
                    select(func.count(Story.id)).where(Story.feature_id == parent.id)
                )
                prefix = f"{parent.prefix}.S{(count or 0) + 1}"
                entity = Story(feature_id=parent.id, prefix=prefix, title=title)

            else:  # task
                if not isinstance(parent, Story):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Issue #{mapping.github_issue_number}: parent issue #{parent_num} is not a story",
                    )
                await self.db.execute(
                    select(Story).where(Story.id == parent.id).with_for_update()
                )
                count = await self.db.scalar(
                    select(func.count(Task.id)).where(Task.story_id == parent.id)
                )
                prefix = f"{parent.prefix}.T{(count or 0) + 1}"
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
