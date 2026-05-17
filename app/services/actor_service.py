from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor
from app.schemas.actor import ActorCreateRequest, ActorUpdateRequest
from app.schemas.requirements import CanvasLayoutRequest, CanvasLayoutResponse


class ActorService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, project_id: uuid.UUID, body: ActorCreateRequest) -> Actor:
        actor = Actor(
            project_id=project_id,
            name=body.name,
            role_description=body.role_description,
        )
        self.db.add(actor)
        await self.db.flush()
        return actor

    async def get(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> Actor:
        result = await self.db.execute(
            select(Actor).where(Actor.id == actor_id, Actor.project_id == project_id)
        )
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy actor")
        return actor

    async def list(self, project_id: uuid.UUID) -> list[Actor]:
        result = await self.db.execute(select(Actor).where(Actor.project_id == project_id))
        return list(result.scalars().all())

    async def update(
        self, project_id: uuid.UUID, actor_id: uuid.UUID, body: ActorUpdateRequest
    ) -> Actor:
        result = await self.db.execute(
            select(Actor).where(Actor.id == actor_id, Actor.project_id == project_id)
        )
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy actor")
        if body.name is not None:
            actor.name = body.name
        if body.role_description is not None:
            actor.role_description = body.role_description
        return actor

    async def delete(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(Actor).where(Actor.id == actor_id, Actor.project_id == project_id)
        )
        actor = result.scalar_one_or_none()
        if not actor:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy actor")
        await self.db.delete(actor)

    async def get_canvas_layout(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> CanvasLayoutResponse:
        actor = await self.get(project_id, actor_id)
        raw = actor.canvas_layout or {}
        return CanvasLayoutResponse(nodes=raw.get("nodes", []))

    async def put_canvas_layout(
        self, project_id: uuid.UUID, actor_id: uuid.UUID, body: CanvasLayoutRequest
    ) -> CanvasLayoutResponse:
        actor = await self.get(project_id, actor_id)
        actor.canvas_layout = body.model_dump(mode="json")
        await self.db.flush()
        return CanvasLayoutResponse(nodes=body.nodes)
