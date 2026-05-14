import re
import secrets
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select
from app.database import get_db
from app.models.organization import Organization, OrgMember
from app.models.user import User
from app.core.responses import ok, created
from app.schemas.organization import (
    AddMemberRequest,
    OrgCreateRequest,
    OrgMemberResponse,
    OrgResponse,
    UserSearchResult,
)
from app.schemas.response import ApiResponse
from app.deps import current_user

router = APIRouter(prefix="/orgs", tags=["organizations"])


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:100] or "org"


async def _unique_slug(db: AsyncSession, base: str, model, scope_col=None, scope_val=None) -> str:
    slug = base
    while True:
        q = select(model).where(model.slug == slug)
        if scope_col is not None:
            q = q.where(scope_col == scope_val)
        if not (await db.execute(q)).scalar_one_or_none():
            return slug
        slug = f"{base}-{secrets.token_hex(3)}"


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


@router.get("/me", response_model=ApiResponse[list[OrgResponse]])
async def list_my_orgs(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == user.id)
    )
    return ok(result.scalars().all())


@router.post("", response_model=ApiResponse[OrgResponse], status_code=status.HTTP_201_CREATED)
async def create_org(
    body: OrgCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    slug = await _unique_slug(db, _slugify(body.name), Organization)
    org = Organization(name=body.name, slug=slug, owner_id=user.id)
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


@router.get("/{org_id}/members/search", response_model=ApiResponse[list[UserSearchResult]])
async def search_users(
    org_id: uuid.UUID,
    q: str = Query(min_length=1, max_length=255),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search users by email or GitHub username to invite as members."""
    await _require_owner(org_id, user, db)
    pattern = f"%{q}%"
    result = await db.execute(
        select(User).where(
            or_(User.email.ilike(pattern), User.github_login.ilike(pattern))
        ).limit(20)
    )
    return ok(result.scalars().all())


@router.post("/{org_id}/members", response_model=ApiResponse[OrgMemberResponse], status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid.UUID,
    body: AddMemberRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_owner(org_id, user, db)

    target = (await db.execute(
        select(User).where(
            or_(User.email == body.identifier, User.github_login == body.identifier)
        )
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found with that email or GitHub username")

    existing = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == target.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="User is already a member")

    member = OrgMember(org_id=org_id, user_id=target.id, role=body.role)
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
