import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.organization import Organization, OrgMember
from app.models.user import User
from app.core.responses import ok, created
from app.schemas.organization import OrgCreateRequest, OrgResponse, OrgMemberResponse, AddMemberRequest
from app.schemas.response import ApiResponse
from app.deps import current_user

router = APIRouter(prefix="/orgs", tags=["organizations"])


async def _require_member(org_id: uuid.UUID, user: User, db: AsyncSession) -> OrgMember:
    result = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user.id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")
    return member


async def _require_owner(org_id: uuid.UUID, user: User, db: AsyncSession) -> OrgMember:
    member = await _require_member(org_id, user, db)
    if member.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return member


@router.post("", response_model=ApiResponse[OrgResponse], status_code=status.HTTP_201_CREATED)
async def create_org(
    body: OrgCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(Organization).where(Organization.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Slug already taken")

    org = Organization(name=body.name, slug=body.slug, owner_id=user.id)
    db.add(org)
    await db.flush()

    membership = OrgMember(org_id=org.id, user_id=user.id, role="owner")
    db.add(membership)
    return created(org)


@router.get("/{org_id}", response_model=ApiResponse[OrgResponse])
async def get_org(
    org_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(org_id, user, db)
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return ok(org)


@router.get("/{org_id}/members", response_model=ApiResponse[list[OrgMemberResponse]])
async def list_members(
    org_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(org_id, user, db)
    result = await db.execute(select(OrgMember).where(OrgMember.org_id == org_id))
    return ok(result.scalars().all())


@router.post("/{org_id}/members", response_model=ApiResponse[OrgMemberResponse], status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid.UUID,
    body: AddMemberRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_owner(org_id, user, db)

    existing = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == body.user_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="User is already a member")

    member = OrgMember(org_id=org_id, user_id=body.user_id, role=body.role)
    db.add(member)
    await db.flush()
    return created(member)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_owner(org_id, user, db)
    result = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Member not found")
    if member.role == "owner":
        owners = await db.execute(
            select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.role == "owner")
        )
        if len(owners.scalars().all()) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot remove the last owner of an organization")
    await db.delete(member)
