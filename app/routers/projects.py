import re
import secrets
import unicodedata
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.project import Project
from app.models.organization import OrgMember
from app.models.user import User
from app.core.responses import ok, created
from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest, ProjectResponse
from app.schemas.response import ApiResponse
from app.deps import current_user

router = APIRouter(prefix="/orgs/{org_id}/projects", tags=["projects"])


def _slugify(name: str) -> str:
    slug = unicodedata.normalize("NFD", name)
    slug = "".join(c for c in slug if unicodedata.category(c) != "Mn")
    slug = slug.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:100] or "project"


async def _require_org_member(org_id: uuid.UUID, user: User, db: AsyncSession) -> OrgMember:
    result = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user.id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")
    return member


async def _require_org_owner(org_id: uuid.UUID, user: User, db: AsyncSession) -> None:
    member = await _require_org_member(org_id, user, db)
    if member.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Owner role required")


@router.post("", response_model=ApiResponse[ProjectResponse], status_code=status.HTTP_201_CREATED)
async def create_project(
    org_id: uuid.UUID,
    body: ProjectCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)

    base = _slugify(body.name)
    slug = base
    while (await db.execute(
        select(Project).where(Project.org_id == org_id, Project.slug == slug)
    )).scalar_one_or_none():
        slug = f"{base}-{secrets.token_hex(3)}"

    project = Project(org_id=org_id, name=body.name, slug=slug, description=body.description)
    db.add(project)
    await db.flush()
    return created(project)


@router.get("", response_model=ApiResponse[list[ProjectResponse]])
async def list_projects(
    org_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    result = await db.execute(select(Project).where(Project.org_id == org_id))
    return ok(result.scalars().all())


@router.get("/{project_id}", response_model=ApiResponse[ProjectResponse])
async def get_project(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ok(project)


@router.patch("/{project_id}", response_model=ApiResponse[ProjectResponse])
async def update_project(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    body: ProjectUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(org_id, user, db)
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    return ok(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_owner(org_id, user, db)
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.org_id == org_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    await db.delete(project)
