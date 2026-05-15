from __future__ import annotations

import uuid

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.crypto import decrypt_token
from app.core.guards import require_sprint
from app.models.github_connection import GithubConnection
from app.models.requirements import Epic, Feature, Story, Task
from app.models.sprint import Sprint, SprintStatus
from app.schemas.sprint import (
    AssignStoriesRequest,
    ReadinessIssue,
    SprintCreateRequest,
    SprintDetailResponse,
    SprintReadinessReport,
    SprintUpdateRequest,
)


class SprintService:
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

    async def create(self, project_id: uuid.UUID, body: SprintCreateRequest) -> Sprint:
        sprint = Sprint(
            project_id=project_id,
            name=body.name,
            goal=body.goal,
            start_date=body.start_date,
            end_date=body.end_date,
        )
        self.db.add(sprint)
        await self.db.flush()
        return sprint

    async def list(self, project_id: uuid.UUID, sprint_status: SprintStatus | None = None) -> list[Sprint]:
        q = select(Sprint).where(Sprint.project_id == project_id)
        if sprint_status:
            q = q.where(Sprint.status == sprint_status)
        q = q.order_by(Sprint.start_date)
        return list((await self.db.execute(q)).scalars().all())

    async def get_detail(self, project_id: uuid.UUID, sprint_id: uuid.UUID) -> SprintDetailResponse:
        sprint = await require_sprint(sprint_id, project_id, self.db)
        stories_result = await self.db.execute(
            select(Story)
            .where(Story.sprint_id == sprint_id)
            .options(selectinload(Story.acceptance_criteria))
            .order_by(Story.prefix)
        )
        stories = list(stories_result.scalars().all())
        resp = SprintDetailResponse.model_validate(sprint)
        resp.stories = stories
        return resp

    async def update(
        self, project_id: uuid.UUID, sprint_id: uuid.UUID, body: SprintUpdateRequest
    ) -> Sprint:
        sprint = await require_sprint(sprint_id, project_id, self.db)
        if body.name is not None:
            sprint.name = body.name
        if body.goal is not None:
            sprint.goal = body.goal
        if body.start_date is not None:
            sprint.start_date = body.start_date
        if body.end_date is not None:
            sprint.end_date = body.end_date
        if body.status is not None:
            sprint.status = body.status
        return sprint

    async def delete(self, project_id: uuid.UUID, sprint_id: uuid.UUID) -> None:
        sprint = await require_sprint(sprint_id, project_id, self.db)
        if sprint.status != SprintStatus.planning:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Only sprints in 'planning' status can be deleted",
            )
        stories_result = await self.db.execute(select(Story).where(Story.sprint_id == sprint_id))
        for story in stories_result.scalars().all():
            story.sprint_id = None
        await self.db.delete(sprint)

    async def assign_stories(
        self, project_id: uuid.UUID, sprint_id: uuid.UUID, body: AssignStoriesRequest
    ) -> Sprint:
        sprint = await require_sprint(sprint_id, project_id, self.db)
        stories_result = await self.db.execute(
            select(Story)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Story.id.in_(body.story_ids), Epic.project_id == project_id)
        )
        found = list(stories_result.scalars().all())
        if len(found) != len(body.story_ids):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Some story IDs do not belong to this project",
            )
        for story in found:
            story.sprint_id = sprint_id
        await self.db.flush()
        return sprint

    async def remove_story(
        self, project_id: uuid.UUID, sprint_id: uuid.UUID, story_id: uuid.UUID
    ) -> None:
        await require_sprint(sprint_id, project_id, self.db)
        result = await self.db.execute(
            select(Story)
            .join(Feature, Story.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Story.id == story_id, Story.sprint_id == sprint_id, Epic.project_id == project_id)
        )
        story = result.scalar_one_or_none()
        if not story:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found in this sprint")
        story.sprint_id = None

    async def readiness(self, project_id: uuid.UUID, sprint_id: uuid.UUID) -> SprintReadinessReport:
        await require_sprint(sprint_id, project_id, self.db)
        stories_result = await self.db.execute(
            select(Story)
            .where(Story.sprint_id == sprint_id)
            .options(selectinload(Story.acceptance_criteria))
            .order_by(Story.prefix)
        )
        stories = list(stories_result.scalars().all())
        issues: list[ReadinessIssue] = []
        for story in stories:
            problems: list[str] = []
            if not story.acceptance_criteria:
                problems.append("missing_acceptance_criteria")
            tasks_result = await self.db.execute(select(Task).where(Task.story_id == story.id))
            tasks = list(tasks_result.scalars().all())
            if tasks and any(t.assignee_id is None for t in tasks):
                problems.append("tasks_missing_assignee")
            if not tasks:
                problems.append("no_tasks_defined")
            if problems:
                issues.append(ReadinessIssue(
                    story_id=story.id,
                    prefix=story.prefix,
                    title=story.title,
                    problems=problems,
                ))
        return SprintReadinessReport(ready=len(issues) == 0, issues=issues)

    async def push_milestone(self, project_id: uuid.UUID, sprint_id: uuid.UUID) -> Sprint:
        conn = await self._require_connection(project_id)
        result = await self.db.execute(
            select(Sprint)
            .where(Sprint.id == sprint_id, Sprint.project_id == project_id)
            .with_for_update()
        )
        sprint = result.scalar_one_or_none()
        if not sprint:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sprint not found")
        if sprint.github_milestone_number is not None:
            return sprint
        token = decrypt_token(conn.access_token)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"https://api.github.com/repos/{conn.repo_owner}/{conn.repo_name}/milestones",
                    json={
                        "title": sprint.name,
                        "due_on": f"{sprint.end_date}T00:00:00Z",
                        "description": sprint.goal or "",
                    },
                    headers=headers,
                    timeout=10,
                )
                resp.raise_for_status()
                sprint.github_milestone_number = resp.json()["number"]
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    detail=f"GitHub API error: {exc.response.status_code}",
                )
            except httpx.RequestError:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="GitHub unreachable")
        await self.db.flush()
        return sprint

    async def close_milestone(self, project_id: uuid.UUID, sprint_id: uuid.UUID) -> Sprint:
        conn = await self._require_connection(project_id)
        sprint = await require_sprint(sprint_id, project_id, self.db)
        if sprint.github_milestone_number is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="No GitHub milestone linked — run push-milestone first",
            )
        token = decrypt_token(conn.access_token)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.patch(
                    f"https://api.github.com/repos/{conn.repo_owner}/{conn.repo_name}/milestones/{sprint.github_milestone_number}",
                    json={"state": "closed"},
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code not in (200, 404):
                    resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    detail=f"GitHub API error: {exc.response.status_code}",
                )
            except httpx.RequestError:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="GitHub unreachable")
        return sprint
