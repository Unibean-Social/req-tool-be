from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project_business import ProjectFlow, ProjectFlowAction, ProjectGoal, ProjectRule
from app.models.stakeholder import Stakeholder
from app.schemas.project_business import (
    ProjectFlowActionCreate,
    ProjectFlowActionResponse,
    ProjectFlowActionUpdate,
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

    async def update_goal(self, project_id: uuid.UUID, goal_id: uuid.UUID, body: ProjectGoalUpdate) -> ProjectGoalResponse:
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
        obj = ProjectFlow(project_id=project_id, code=body.code, name=body.name, description=body.description)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj, ["actions"])
        return ProjectFlowResponse.model_validate(obj)

    async def list_flows(self, project_id: uuid.UUID) -> list[ProjectFlowResponse]:
        result = await self.db.execute(
            select(ProjectFlow)
            .where(ProjectFlow.project_id == project_id)
            .options(selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.rules))
        )
        return [ProjectFlowResponse.model_validate(f) for f in result.scalars().all()]

    async def update_flow(self, project_id: uuid.UUID, flow_id: uuid.UUID, body: ProjectFlowUpdate) -> ProjectFlowResponse:
        result = await self.db.execute(
            select(ProjectFlow)
            .where(ProjectFlow.id == flow_id, ProjectFlow.project_id == project_id)
            .options(selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.rules))
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow")
        if body.name is not None:
            obj.name = body.name
        if body.code is not None:
            obj.code = body.code
        if "description" in body.model_fields_set:
            obj.description = body.description
        return ProjectFlowResponse.model_validate(obj)

    async def delete_flow(self, project_id: uuid.UUID, flow_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ProjectFlow).where(ProjectFlow.id == flow_id, ProjectFlow.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow")
        await self.db.delete(obj)

    # ── Flow Actions ─────────────────────────────────────────────────────────

    async def _get_flow_in_project(self, project_id: uuid.UUID, flow_id: uuid.UUID) -> ProjectFlow:
        result = await self.db.execute(
            select(ProjectFlow).where(ProjectFlow.id == flow_id, ProjectFlow.project_id == project_id)
        )
        flow = result.scalar_one_or_none()
        if not flow:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow")
        return flow

    async def _validate_actor_in_project(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(Stakeholder).where(Stakeholder.id == actor_id, Stakeholder.project_id == project_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="actor_id không thuộc project này")

    async def create_flow_action(self, project_id: uuid.UUID, flow_id: uuid.UUID, body: ProjectFlowActionCreate) -> ProjectFlowActionResponse:
        await self._get_flow_in_project(project_id, flow_id)
        if body.actor_id is not None:
            await self._validate_actor_in_project(project_id, body.actor_id)
        obj = ProjectFlowAction(
            flow_id=flow_id, order=body.order, description=body.description, actor_id=body.actor_id
        )
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj, ["rules"])
        return ProjectFlowActionResponse.model_validate(obj)

    async def update_flow_action(self, project_id: uuid.UUID, flow_id: uuid.UUID, action_id: uuid.UUID, body: ProjectFlowActionUpdate) -> ProjectFlowActionResponse:
        await self._get_flow_in_project(project_id, flow_id)
        result = await self.db.execute(
            select(ProjectFlowAction)
            .where(ProjectFlowAction.id == action_id, ProjectFlowAction.flow_id == flow_id)
            .options(selectinload(ProjectFlowAction.rules))
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow action")
        if body.order is not None:
            obj.order = body.order
        if body.description is not None:
            obj.description = body.description
        if "actor_id" in body.model_fields_set:
            if body.actor_id is not None:
                await self._validate_actor_in_project(project_id, body.actor_id)
            obj.actor_id = body.actor_id
        await self.db.flush()
        result2 = await self.db.execute(
            select(ProjectFlowAction)
            .where(ProjectFlowAction.id == action_id)
            .options(selectinload(ProjectFlowAction.rules))
        )
        return ProjectFlowActionResponse.model_validate(result2.scalar_one())

    async def delete_flow_action(self, project_id: uuid.UUID, flow_id: uuid.UUID, action_id: uuid.UUID) -> None:
        await self._get_flow_in_project(project_id, flow_id)
        result = await self.db.execute(
            select(ProjectFlowAction)
            .where(ProjectFlowAction.id == action_id, ProjectFlowAction.flow_id == flow_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow action")
        await self.db.delete(obj)

    async def add_rule_to_action(self, project_id: uuid.UUID, flow_id: uuid.UUID, action_id: uuid.UUID, rule_id: uuid.UUID) -> ProjectFlowActionResponse:
        await self._get_flow_in_project(project_id, flow_id)
        result = await self.db.execute(
            select(ProjectFlowAction)
            .where(ProjectFlowAction.id == action_id, ProjectFlowAction.flow_id == flow_id)
            .options(selectinload(ProjectFlowAction.rules))
        )
        action = result.scalar_one_or_none()
        if not action:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow action")
        rule_result = await self.db.execute(
            select(ProjectRule).where(ProjectRule.id == rule_id, ProjectRule.project_id == project_id)
        )
        rule = rule_result.scalar_one_or_none()
        if not rule:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy rule")
        if rule not in action.rules:
            action.rules.append(rule)
            await self.db.flush()
        return ProjectFlowActionResponse.model_validate(action)

    async def remove_rule_from_action(self, project_id: uuid.UUID, flow_id: uuid.UUID, action_id: uuid.UUID, rule_id: uuid.UUID) -> None:
        await self._get_flow_in_project(project_id, flow_id)
        result = await self.db.execute(
            select(ProjectFlowAction)
            .where(ProjectFlowAction.id == action_id, ProjectFlowAction.flow_id == flow_id)
            .options(selectinload(ProjectFlowAction.rules))
        )
        action = result.scalar_one_or_none()
        if not action:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow action")
        matched = [r for r in action.rules if r.id == rule_id]
        if not matched:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không được liên kết với action này")
        action.rules = [r for r in action.rules if r.id != rule_id]
        await self.db.flush()

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

    async def update_rule(self, project_id: uuid.UUID, rule_id: uuid.UUID, body: ProjectRuleUpdate) -> ProjectRuleResponse:
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
