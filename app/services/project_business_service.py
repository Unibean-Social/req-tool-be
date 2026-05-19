from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_business import ProjectFlow, ProjectGoal, ProjectRule
from app.schemas.project_business import (
    ProjectFlowCreate,
    ProjectFlowResponse,
    ProjectFlowUpdate,
    ProjectGoalCreate,
    ProjectGoalResponse,
    ProjectGoalUpdate,
    ProjectRuleCreate,
    ProjectRuleResponse,
    ProjectRuleUpdate,
)


class ProjectBusinessService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Goals ────────────────────────────────────────────────────────────────

    async def create_goal(self, project_id: uuid.UUID, body: ProjectGoalCreate) -> ProjectGoalResponse:
        obj = ProjectGoal(project_id=project_id, description=body.description, order=body.order)
        self.db.add(obj)
        await self.db.flush()
        return ProjectGoalResponse.model_validate(obj)

    async def list_goals(self, project_id: uuid.UUID) -> list[ProjectGoalResponse]:
        result = await self.db.execute(
            select(ProjectGoal).where(ProjectGoal.project_id == project_id).order_by(ProjectGoal.order)
        )
        return [ProjectGoalResponse.model_validate(g) for g in result.scalars().all()]

    async def update_goal(
        self, project_id: uuid.UUID, goal_id: uuid.UUID, body: ProjectGoalUpdate
    ) -> ProjectGoalResponse:
        result = await self.db.execute(
            select(ProjectGoal).where(ProjectGoal.id == goal_id, ProjectGoal.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy goal")
        if body.description is not None:
            obj.description = body.description
        if body.order is not None:
            obj.order = body.order
        return ProjectGoalResponse.model_validate(obj)

    async def delete_goal(self, project_id: uuid.UUID, goal_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ProjectGoal).where(ProjectGoal.id == goal_id, ProjectGoal.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy goal")
        await self.db.delete(obj)

    # ── Flows ────────────────────────────────────────────────────────────────

    async def create_flow(self, project_id: uuid.UUID, body: ProjectFlowCreate) -> ProjectFlowResponse:
        obj = ProjectFlow(
            project_id=project_id, title=body.title, description=body.description, order=body.order
        )
        self.db.add(obj)
        await self.db.flush()
        return ProjectFlowResponse.model_validate(obj)

    async def list_flows(self, project_id: uuid.UUID) -> list[ProjectFlowResponse]:
        result = await self.db.execute(
            select(ProjectFlow).where(ProjectFlow.project_id == project_id).order_by(ProjectFlow.order)
        )
        return [ProjectFlowResponse.model_validate(f) for f in result.scalars().all()]

    async def update_flow(
        self, project_id: uuid.UUID, flow_id: uuid.UUID, body: ProjectFlowUpdate
    ) -> ProjectFlowResponse:
        result = await self.db.execute(
            select(ProjectFlow).where(ProjectFlow.id == flow_id, ProjectFlow.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow")
        if body.title is not None:
            obj.title = body.title
        if body.description is not None:
            obj.description = body.description
        if body.order is not None:
            obj.order = body.order
        return ProjectFlowResponse.model_validate(obj)

    async def delete_flow(self, project_id: uuid.UUID, flow_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ProjectFlow).where(ProjectFlow.id == flow_id, ProjectFlow.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow")
        await self.db.delete(obj)

    # ── Rules ────────────────────────────────────────────────────────────────

    async def create_rule(self, project_id: uuid.UUID, body: ProjectRuleCreate) -> ProjectRuleResponse:
        obj = ProjectRule(
            project_id=project_id,
            rule_def=body.rule_def,
            type=body.type,
            is_dynamic=body.is_dynamic,
            source=body.source,
        )
        self.db.add(obj)
        await self.db.flush()
        return ProjectRuleResponse.model_validate(obj)

    async def list_rules(self, project_id: uuid.UUID) -> list[ProjectRuleResponse]:
        result = await self.db.execute(
            select(ProjectRule).where(ProjectRule.project_id == project_id).order_by(ProjectRule.created_at)
        )
        return [ProjectRuleResponse.model_validate(r) for r in result.scalars().all()]

    async def update_rule(
        self, project_id: uuid.UUID, rule_id: uuid.UUID, body: ProjectRuleUpdate
    ) -> ProjectRuleResponse:
        result = await self.db.execute(
            select(ProjectRule).where(ProjectRule.id == rule_id, ProjectRule.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy rule")
        if body.rule_def is not None:
            obj.rule_def = body.rule_def
        if body.type is not None:
            obj.type = body.type
        if body.is_dynamic is not None:
            obj.is_dynamic = body.is_dynamic
        if body.source is not None:
            obj.source = body.source
        return ProjectRuleResponse.model_validate(obj)

    async def delete_rule(self, project_id: uuid.UUID, rule_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ProjectRule).where(ProjectRule.id == rule_id, ProjectRule.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy rule")
        await self.db.delete(obj)
