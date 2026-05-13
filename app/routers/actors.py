import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.actor import Actor
from app.models.project import Project
from app.models.organization import OrgMember
from app.models.user import User
from app.core.responses import ok, created
from app.schemas.actor import ActorCreateRequest, ActorUpdateRequest, ActorResponse
from app.schemas.response import ApiResponse
from app.deps import current_user

router = APIRouter(prefix="/projects/{project_id}/actors", tags=["actors"])


async def _require_project_access(project_id: uuid.UUID, user: User, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")

    member_result = await db.execute(
        select(OrgMember).where(OrgMember.org_id == project.org_id, OrgMember.user_id == user.id)
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of this project's organization")
    return project


@router.post("", response_model=ApiResponse[ActorResponse], status_code=status.HTTP_201_CREATED)
async def create_actor(
    project_id: uuid.UUID,
    body: ActorCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    actor = Actor(project_id=project_id, name=body.name, role_description=body.role_description)
    db.add(actor)
    await db.flush()
    return created(actor)


@router.get("", response_model=ApiResponse[list[ActorResponse]])
async def list_actors(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(Actor).where(Actor.project_id == project_id))
    return ok(result.scalars().all())


@router.patch("/{actor_id}", response_model=ApiResponse[ActorResponse])
async def update_actor(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: ActorUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Actor).where(Actor.id == actor_id, Actor.project_id == project_id)
    )
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Actor not found")

    if body.name is not None:
        actor.name = body.name
    if body.role_description is not None:
        actor.role_description = body.role_description
    return ok(actor)


@router.delete("/{actor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_actor(
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(
        select(Actor).where(Actor.id == actor_id, Actor.project_id == project_id)
    )
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Actor not found")
    await db.delete(actor)
