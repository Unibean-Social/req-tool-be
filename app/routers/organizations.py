import re
import secrets
import unicodedata
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.organization import Organization, OrgMember
from app.models.project import Project
from app.models.user import User
from app.core.responses import ok, created
from app.schemas.organization import (
    AddMemberRequest,
    OrgCreateRequest,
    OrgMemberResponse,
    OrgResponse,
    OrgStats,
    BulkAddMemberResponse,
)
from app.schemas.response import ApiResponse
from app.deps import current_user

router = APIRouter(prefix="/orgs", tags=["organizations"])


def _slugify(name: str) -> str:
    slug = name.translate(str.maketrans("đĐ", "dD"))
    slug = unicodedata.normalize("NFD", slug)
    slug = "".join(c for c in slug if unicodedata.category(c) != "Mn")
    slug = slug.lower().strip()
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


async def _fetch_stats(db: AsyncSession, org_ids: list) -> dict:
    member_q = (
        select(OrgMember.org_id, func.count().label("cnt"))
        .where(OrgMember.org_id.in_(org_ids))
        .group_by(OrgMember.org_id)
    )
    project_q = (
        select(Project.org_id, func.count().label("cnt"))
        .where(Project.org_id.in_(org_ids))
        .group_by(Project.org_id)
    )
    members = {r.org_id: r.cnt for r in (await db.execute(member_q)).all()}
    projects = {r.org_id: r.cnt for r in (await db.execute(project_q)).all()}
    return {
        oid: OrgStats(member_count=members.get(oid, 0), project_count=projects.get(oid, 0))
        for oid in org_ids
    }


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
    orgs = result.scalars().all()
    stats = await _fetch_stats(db, [o.id for o in orgs])
    return ok([OrgResponse.model_validate(o).model_copy(update={"stats": stats[o.id]}) for o in orgs])


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
    stats = await _fetch_stats(db, [org.id])
    return ok(OrgResponse.model_validate(org).model_copy(update={"stats": stats[org.id]}))


@router.get("/{org_id}/members", response_model=ApiResponse[list[OrgMemberResponse]])
async def list_members(
    org_id: uuid.UUID,
    q: str | None = Query(default=None, min_length=1, max_length=255),
    role: str | None = Query(default=None, pattern="^(owner|member)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(org_id, user, db)
    stmt = (
        select(OrgMember)
        .where(OrgMember.org_id == org_id)
        .options(selectinload(OrgMember.user))
        .join(User, User.id == OrgMember.user_id)
    )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(User.email.ilike(pattern), User.github_login.ilike(pattern), User.full_name.ilike(pattern))
        )
    if role:
        stmt = stmt.where(OrgMember.role == role)
    stmt = stmt.order_by(OrgMember.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return ok(result.scalars().all())



@router.post("/{org_id}/members", response_model=ApiResponse[BulkAddMemberResponse], status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid.UUID,
    body: AddMemberRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_owner(org_id, user, db)

    added: list[OrgMemberResponse] = []
    skipped: list[str] = []
    not_found: list[str] = []

    for item in body.members:
        target = (await db.execute(
            select(User).where(
                or_(User.email == item.identifier, User.github_login == item.identifier)
            )
        )).scalar_one_or_none()

        if not target:
            not_found.append(item.identifier)
            continue

        existing = (await db.execute(
            select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == target.id)
        )).scalar_one_or_none()

        if existing:
            skipped.append(item.identifier)
            continue

        member = OrgMember(org_id=org_id, user_id=target.id, role=item.role)
        db.add(member)
        await db.flush()
        member.user = target
        added.append(member)

    return created(BulkAddMemberResponse(added=added, skipped=skipped, not_found=not_found))


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
