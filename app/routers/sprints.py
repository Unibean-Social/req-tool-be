import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.crypto import decrypt_token
from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user
from app.models.github_connection import GithubConnection
from app.models.organization import OrgMember
from app.models.project import Project
from app.models.requirements import AcceptanceCriteria, Epic, Feature, ItemStatus, Story, Task
from app.models.sprint import Sprint, SprintStatus
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.sprint import (
    AssignStoriesRequest,
    SprintCreateRequest,
    SprintDetailResponse,
    SprintReadinessReport,
    SprintResponse,
    SprintUpdateRequest,
    ReadinessIssue,
)

router = APIRouter(prefix="/projects/{project_id}/sprints", tags=["sprints"])

_GITHUB_MILESTONES_URL = "https://api.github.com/repos/{owner}/{repo}/milestones"


# ── Guards ─────────────────────────────────────────────────────────────────────


async def _require_project_member(project_id: uuid.UUID, user: User, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    member = await db.execute(
        select(OrgMember).where(OrgMember.org_id == project.org_id, OrgMember.user_id == user.id)
    )
    if not member.scalar_one_or_none():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")
    return project


async def _require_sprint(sprint_id: uuid.UUID, project_id: uuid.UUID, db: AsyncSession) -> Sprint:
    result = await db.execute(
        select(Sprint).where(Sprint.id == sprint_id, Sprint.project_id == project_id)
    )
    sprint = result.scalar_one_or_none()
    if not sprint:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    return sprint


async def _require_connection(project_id: uuid.UUID, db: AsyncSession) -> GithubConnection:
    result = await db.execute(select(GithubConnection).where(GithubConnection.project_id == project_id))
    conn = result.scalar_one_or_none()
    if not conn or not conn.access_token:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No GitHub connection — connect the project first")
    return conn


# ── CRUD ───────────────────────────────────────────────────────────────────────


@router.post("", response_model=ApiResponse[SprintResponse], status_code=status.HTTP_201_CREATED)
async def create_sprint(
    project_id: uuid.UUID,
    body: SprintCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    sprint = Sprint(
        project_id=project_id,
        name=body.name,
        goal=body.goal,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    db.add(sprint)
    await db.flush()
    return created(sprint)


@router.get("", response_model=ApiResponse[list[SprintResponse]])
async def list_sprints(
    project_id: uuid.UUID,
    status: SprintStatus | None = Query(None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    q = select(Sprint).where(Sprint.project_id == project_id)
    if status:
        q = q.where(Sprint.status == status)
    q = q.order_by(Sprint.start_date)
    result = await db.execute(q)
    return ok(result.scalars().all())


@router.get("/{sprint_id}", response_model=ApiResponse[SprintDetailResponse])
async def get_sprint(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    sprint = await _require_sprint(sprint_id, project_id, db)

    stories_result = await db.execute(
        select(Story)
        .where(Story.sprint_id == sprint_id)
        .options(selectinload(Story.acceptance_criteria))
        .order_by(Story.prefix)
    )
    stories = stories_result.scalars().all()

    resp = SprintDetailResponse.model_validate(sprint)
    resp.stories = [s for s in stories]
    return ok(resp)


@router.patch("/{sprint_id}", response_model=ApiResponse[SprintResponse])
async def update_sprint(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    body: SprintUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    sprint = await _require_sprint(sprint_id, project_id, db)
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
    return ok(sprint)


@router.delete("/{sprint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sprint(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    sprint = await _require_sprint(sprint_id, project_id, db)
    if sprint.status != SprintStatus.planning:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Only sprints in 'planning' status can be deleted")

    # Clear sprint_id on assigned stories
    stories_result = await db.execute(select(Story).where(Story.sprint_id == sprint_id))
    for story in stories_result.scalars().all():
        story.sprint_id = None

    await db.delete(sprint)


# ── Story assignment ───────────────────────────────────────────────────────────


@router.post("/{sprint_id}/stories", response_model=ApiResponse[SprintResponse])
async def assign_stories(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    body: AssignStoriesRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    sprint = await _require_sprint(sprint_id, project_id, db)

    # Validate all stories belong to this project
    stories_result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id.in_(body.story_ids), Epic.project_id == project_id)
    )
    found = stories_result.scalars().all()
    if len(found) != len(body.story_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Some story IDs do not belong to this project",
        )
    for story in found:
        story.sprint_id = sprint_id

    await db.flush()
    return ok(sprint)


@router.delete("/{sprint_id}/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_story_from_sprint(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    story_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    await _require_sprint(sprint_id, project_id, db)

    result = await db.execute(
        select(Story)
        .join(Feature, Story.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Story.id == story_id, Story.sprint_id == sprint_id, Epic.project_id == project_id)
    )
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Story not found in this sprint")
    story.sprint_id = None


# ── Readiness check ────────────────────────────────────────────────────────────


@router.get("/{sprint_id}/readiness", response_model=ApiResponse[SprintReadinessReport])
async def sprint_readiness(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    await _require_sprint(sprint_id, project_id, db)

    stories_result = await db.execute(
        select(Story)
        .where(Story.sprint_id == sprint_id)
        .options(selectinload(Story.acceptance_criteria))
        .order_by(Story.prefix)
    )
    stories = stories_result.scalars().all()

    issues: list[ReadinessIssue] = []
    for story in stories:
        problems: list[str] = []
        if not story.acceptance_criteria:
            problems.append("missing_acceptance_criteria")

        # Check tasks have assignees
        tasks_result = await db.execute(select(Task).where(Task.story_id == story.id))
        tasks = tasks_result.scalars().all()
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

    return ok(SprintReadinessReport(ready=len(issues) == 0, issues=issues))


# ── GitHub milestone sync ──────────────────────────────────────────────────────


@router.post("/{sprint_id}/push-milestone", response_model=ApiResponse[SprintResponse])
async def push_milestone(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    conn = await _require_connection(project_id, db)

    # SELECT FOR UPDATE to prevent concurrent double-create
    result = await db.execute(
        select(Sprint)
        .where(Sprint.id == sprint_id, Sprint.project_id == project_id)
        .with_for_update()
    )
    sprint = result.scalar_one_or_none()
    if not sprint:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sprint not found")

    if sprint.github_milestone_number is not None:
        return ok(sprint)  # idempotent

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
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"GitHub API error: {exc.response.status_code}")
        except httpx.RequestError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="GitHub unreachable")

    sprint.github_milestone_number = resp.json()["number"]
    await db.flush()
    return ok(sprint)


@router.post("/{sprint_id}/close-milestone", response_model=ApiResponse[SprintResponse])
async def close_milestone(
    project_id: uuid.UUID,
    sprint_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_member(project_id, user, db)
    conn = await _require_connection(project_id, db)
    sprint = await _require_sprint(sprint_id, project_id, db)

    if sprint.github_milestone_number is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No GitHub milestone linked — run push-milestone first")

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
            # 404 = already deleted on GitHub — treat as success (idempotent)
            if resp.status_code not in (200, 404):
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"GitHub API error: {exc.response.status_code}")
        except httpx.RequestError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="GitHub unreachable")

    return ok(sprint)
