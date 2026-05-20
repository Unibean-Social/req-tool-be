from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.project_business import (
    ProjectBusinessRequirement,
    ProjectConstraint,
    ProjectFlow,
    ProjectFlowAction,
    ProjectGoal,
    ProjectGoalObjective,
    ProjectRule,
)
from app.models.stakeholder import Stakeholder
from app.utils.notation_detector import detect_notation
from app.utils.swimlane_layout import (
    calculate_layout,
    layout_to_swimlane_dict,
    review_positions,
)

_DEFAULT_LANE = "lane-default"
from app.schemas.project_business import (
    ProjectBusinessRequirementCreate,
    ProjectBusinessRequirementResponse,
    ProjectBusinessRequirementUpdate,
    ProjectConstraintCreate,
    ProjectConstraintResponse,
    ProjectConstraintUpdate,
    ProjectFlowActionCreate,
    ProjectFlowActionResponse,
    ProjectFlowActionUpdate,
    ProjectFlowCreate,
    ProjectFlowDetailResponse,
    ProjectFlowResponse,
    ProjectFlowUpdate,
    ProjectGoalCreate,
    ProjectGoalResponse,
    ProjectGoalUpdate,
    ProjectRuleCreate,
    ProjectRuleResponse,
    ProjectRuleUpdate,
    SwimlaneRequest,
)


class ProjectBusinessService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Goals ────────────────────────────────────────────────────────────────

    async def create_goal(self, project_id: uuid.UUID, body: ProjectGoalCreate) -> ProjectGoalResponse:
        obj = ProjectGoal(
            project_id=project_id,
            description=body.description,
            order=body.order,
            priority=body.priority,
            success_metric=body.success_metric,
            target_date=body.target_date,
        )
        self.db.add(obj)
        await self.db.flush()
        if body.objectives:
            self.db.add_all([ProjectGoalObjective(goal_id=obj.id, description=d) for d in body.objectives])
            await self.db.flush()
        await self.db.refresh(obj, attribute_names=["objectives"])
        return ProjectGoalResponse.model_validate(obj)

    async def list_goals(self, project_id: uuid.UUID) -> list[ProjectGoalResponse]:
        result = await self.db.execute(
            select(ProjectGoal)
            .where(ProjectGoal.project_id == project_id)
            .options(selectinload(ProjectGoal.objectives))
            .order_by(ProjectGoal.order)
        )
        return [ProjectGoalResponse.model_validate(g) for g in result.scalars().all()]

    async def update_goal(self, project_id: uuid.UUID, goal_id: uuid.UUID, body: ProjectGoalUpdate) -> ProjectGoalResponse:
        result = await self.db.execute(
            select(ProjectGoal)
            .where(ProjectGoal.id == goal_id, ProjectGoal.project_id == project_id)
            .options(selectinload(ProjectGoal.objectives))
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy goal")
        if body.description is not None:
            obj.description = body.description
        if body.order is not None:
            obj.order = body.order
        if body.priority is not None:
            obj.priority = body.priority
        if body.success_metric is not None:
            obj.success_metric = body.success_metric
        if body.target_date is not None:
            obj.target_date = body.target_date
        if body.objectives is not None:
            for existing in list(obj.objectives):
                await self.db.delete(existing)
            await self.db.flush()
            if body.objectives:
                self.db.add_all([ProjectGoalObjective(goal_id=obj.id, description=d) for d in body.objectives])
                await self.db.flush()
            await self.db.refresh(obj, attribute_names=["objectives"])
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

    async def create_flow(self, project_id: uuid.UUID, body: ProjectFlowCreate) -> ProjectFlowDetailResponse:
        obj = ProjectFlow(project_id=project_id, code=body.code, name=body.name, description=body.description)
        self.db.add(obj)
        await self.db.flush()

        if body.actions:
            actor_ids = {item.actor_id for item in body.actions if item.actor_id is not None}
            for actor_id in actor_ids:
                await self._validate_actor_in_project(project_id, actor_id)
            action_objs = [
                ProjectFlowAction(flow_id=obj.id, order=item.order, description=item.description, actor_id=item.actor_id)
                for item in body.actions
            ]
            self.db.add_all(action_objs)
            await self.db.flush()
            for action_obj, item in zip(action_objs, body.actions):
                if item.rule_ids:
                    await self.db.refresh(action_obj, attribute_names=["rules"])
                    action_obj.rules = await self._resolve_rules(project_id, item.rule_ids)
            await self.db.flush()

        flow = await self._load_flow_for_swimlane(obj.id)
        if body.actions:
            await self._auto_generate_swimlane(flow)
        return ProjectFlowDetailResponse.model_validate(flow)

    async def list_flows(self, project_id: uuid.UUID) -> list[ProjectFlowResponse]:
        result = await self.db.execute(
            select(ProjectFlow)
            .where(ProjectFlow.project_id == project_id)
            .options(selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.rules))
        )
        return [ProjectFlowResponse.model_validate(f) for f in result.scalars().all()]

    async def list_flow_templates(self, project_id: uuid.UUID) -> list:
        from app.schemas.project_business import (
            FlowTemplateActorResponse,
            FlowTemplateResponse,
            FlowTemplateStepResponse,
        )

        result = await self.db.execute(
            select(ProjectFlow)
            .where(ProjectFlow.project_id == project_id)
            .options(
                selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.actor)
            )
            .order_by(ProjectFlow.code)
        )
        flows = result.scalars().all()

        templates = []
        for flow in flows:
            seen_actor_ids: dict[uuid.UUID, str] = {}
            steps = []
            for action in sorted(flow.actions, key=lambda a: a.order):
                actor_name: str | None = None
                if action.actor_id and action.actor:
                    actor_name = action.actor.name
                    seen_actor_ids[action.actor_id] = action.actor.name
                steps.append(FlowTemplateStepResponse(
                    step=action.order + 1,
                    description=action.description,
                    actor=actor_name,
                ))
            actors = [
                FlowTemplateActorResponse(id=aid, name=name)
                for aid, name in seen_actor_ids.items()
            ]
            templates.append(FlowTemplateResponse(
                id=flow.id,
                code=flow.code,
                name=flow.name,
                actors=actors,
                steps=steps,
            ))
        return templates

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

    async def get_flow(self, project_id: uuid.UUID, flow_id: uuid.UUID) -> ProjectFlowDetailResponse:
        result = await self.db.execute(
            select(ProjectFlow)
            .where(ProjectFlow.id == flow_id, ProjectFlow.project_id == project_id)
            .options(selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.rules))
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow")
        return ProjectFlowDetailResponse.model_validate(obj)

    async def update_swimlane(
        self, project_id: uuid.UUID, flow_id: uuid.UUID, payload: SwimlaneRequest
    ) -> ProjectFlowDetailResponse:
        result = await self.db.execute(
            select(ProjectFlow)
            .where(ProjectFlow.id == flow_id, ProjectFlow.project_id == project_id)
            .options(selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.rules))
        )
        flow = result.scalar_one_or_none()
        if not flow:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow")

        action_map = {a.id: a for a in flow.actions}
        unknown = {item.id for item in payload.actions} - set(action_map.keys())
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"action IDs không thuộc flow này: {[str(u) for u in unknown]}",
            )

        enriched_actions = []
        for item in payload.actions:
            db_action = action_map[item.id]
            notation = await detect_notation(
                db_action.description or "",
                access_key=settings.aws_access_key_id,
                secret_key=settings.aws_secret_access_key,
                region=settings.aws_region,
                model_id=settings.bedrock_notation_model,
            )
            enriched_actions.append({
                "id": str(item.id),
                "lane_id": item.lane_id,
                "notation": notation,
                "index": item.index,
                "x": item.x,
                "y": item.y,
                "width": item.width,
                "height": item.height,
                "label": item.label if item.label is not None else (db_action.description or ""),
            })

        data = payload.model_dump(mode="json")
        data["id"] = str(flow_id)
        data["actions"] = enriched_actions

        existing_lanes: dict[str, dict] = {}
        if flow.swimlane and isinstance(flow.swimlane, dict):
            for l in flow.swimlane.get("lanes", []):
                existing_lanes[l["id"]] = l
        for lane in data["lanes"]:
            prev = existing_lanes.get(lane["id"], {})
            if lane.get("width") is None and prev.get("width") is not None:
                lane["width"] = prev["width"]
            if lane.get("x_left") is None and prev.get("x_left") is not None:
                lane["x_left"] = prev["x_left"]

        flow.swimlane = data
        await self.db.flush()
        refreshed = await self.db.execute(
            select(ProjectFlow)
            .where(ProjectFlow.id == flow_id)
            .options(selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.rules))
        )
        return ProjectFlowDetailResponse.model_validate(refreshed.scalar_one())

    # ── Flow Actions ─────────────────────────────────────────────────────────

    async def _get_flow_in_project(self, project_id: uuid.UUID, flow_id: uuid.UUID) -> ProjectFlow:
        result = await self.db.execute(
            select(ProjectFlow).where(ProjectFlow.id == flow_id, ProjectFlow.project_id == project_id)
        )
        flow = result.scalar_one_or_none()
        if not flow:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy flow")
        return flow

    async def _load_flow_for_swimlane(self, flow_id: uuid.UUID) -> ProjectFlow:
        result = await self.db.execute(
            select(ProjectFlow)
            .where(ProjectFlow.id == flow_id)
            .options(
                selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.rules),
                selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.actor),
            )
        )
        return result.scalar_one()

    async def _auto_generate_swimlane(self, flow: ProjectFlow) -> None:
        # Stage 2: build lane order (preserve insertion order by action.order)
        sorted_actions = sorted(flow.actions, key=lambda a: a.order)
        seen: dict[str, str] = {}
        for action in sorted_actions:
            lid = f"lane-{action.actor_id}" if action.actor_id else _DEFAULT_LANE
            if lid not in seen:
                seen[lid] = action.actor.name if action.actor else lid
        if not seen:
            seen[_DEFAULT_LANE] = "Chung"

        lane_ids = list(seen.keys())

        # Stage 3: detect notations
        actions_with_notation: list[dict] = []
        for i, action in enumerate(sorted_actions):
            notation = await detect_notation(
                action.description or "",
                access_key=settings.aws_access_key_id,
                secret_key=settings.aws_secret_access_key,
                region=settings.aws_region,
                model_id=settings.bedrock_notation_model,
            )
            lane_id = f"lane-{action.actor_id}" if action.actor_id else _DEFAULT_LANE
            actions_with_notation.append({
                "id": str(action.id),
                "lane_id": lane_id,
                "notation": notation,
                "label": action.description or "",
                "order": action.order,
            })

        # Stage 4: calculate positions
        layout = calculate_layout(actions_with_notation, lane_ids)

        # Stage 5: review and auto-fix
        layout = await review_positions(
            layout,
            access_key=settings.aws_access_key_id,
            secret_key=settings.aws_secret_access_key,
            region=settings.aws_region,
            model_id=settings.bedrock_notation_model,
        )

        # Stage 6: finalize
        swimlane = layout_to_swimlane_dict(layout, str(flow.id), flow.name)
        # Restore lane titles from seen map
        for lane in swimlane["lanes"]:
            lane["title"] = seen.get(lane["id"], lane["id"])
        flow.swimlane = swimlane

    async def _validate_actor_in_project(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(Stakeholder).where(Stakeholder.id == actor_id, Stakeholder.project_id == project_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="actor_id không thuộc project này")

    async def _resolve_rules(self, project_id: uuid.UUID, rule_ids: list[uuid.UUID]) -> list[ProjectRule]:
        result = await self.db.execute(
            select(ProjectRule).where(ProjectRule.id.in_(rule_ids), ProjectRule.project_id == project_id)
        )
        rules = result.scalars().all()
        missing = set(rule_ids) - {r.id for r in rules}
        if missing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Không tìm thấy rule: {[str(m) for m in missing]}")
        return list(rules)

    async def create_flow_actions(
        self, project_id: uuid.UUID, flow_id: uuid.UUID, items: list[ProjectFlowActionCreate]
    ) -> list[ProjectFlowActionResponse]:
        await self._get_flow_in_project(project_id, flow_id)
        actor_ids = {item.actor_id for item in items if item.actor_id is not None}
        for actor_id in actor_ids:
            await self._validate_actor_in_project(project_id, actor_id)
        objs = [
            ProjectFlowAction(
                flow_id=flow_id, order=item.order, description=item.description, actor_id=item.actor_id
            )
            for item in items
        ]
        self.db.add_all(objs)
        await self.db.flush()
        for obj, item in zip(objs, items):
            if item.rule_ids:
                await self.db.refresh(obj, attribute_names=["rules"])
                obj.rules = await self._resolve_rules(project_id, item.rule_ids)
        await self.db.flush()

        flow = await self._load_flow_for_swimlane(flow_id)
        await self._auto_generate_swimlane(flow)

        ids = [obj.id for obj in objs]
        result = await self.db.execute(
            select(ProjectFlowAction)
            .where(ProjectFlowAction.id.in_(ids))
            .options(selectinload(ProjectFlowAction.rules))
            .order_by(ProjectFlowAction.order)
        )
        return [ProjectFlowActionResponse.model_validate(o) for o in result.scalars().all()]

    async def update_flow_actions(
        self, project_id: uuid.UUID, flow_id: uuid.UUID, items: list[ProjectFlowActionUpdate]
    ) -> list[ProjectFlowActionResponse]:
        await self._get_flow_in_project(project_id, flow_id)
        action_ids = [item.id for item in items]
        result = await self.db.execute(
            select(ProjectFlowAction)
            .where(ProjectFlowAction.id.in_(action_ids), ProjectFlowAction.flow_id == flow_id)
            .options(selectinload(ProjectFlowAction.rules))
        )
        action_map = {obj.id: obj for obj in result.scalars().all()}
        missing = set(action_ids) - set(action_map.keys())
        if missing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Không tìm thấy flow action: {[str(m) for m in missing]}")

        for item in items:
            obj = action_map[item.id]
            if item.order is not None:
                obj.order = item.order
            if item.description is not None:
                obj.description = item.description
            if "actor_id" in item.model_fields_set:
                if item.actor_id is not None:
                    await self._validate_actor_in_project(project_id, item.actor_id)
                obj.actor_id = item.actor_id
            if item.rule_ids is not None:
                obj.rules = await self._resolve_rules(project_id, item.rule_ids)
        await self.db.flush()

        flow = await self._load_flow_for_swimlane(flow_id)
        await self._auto_generate_swimlane(flow)

        result2 = await self.db.execute(
            select(ProjectFlowAction)
            .where(ProjectFlowAction.id.in_(action_ids))
            .options(selectinload(ProjectFlowAction.rules))
            .order_by(ProjectFlowAction.order)
        )
        return [ProjectFlowActionResponse.model_validate(o) for o in result2.scalars().all()]

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
        await self.db.flush()

        flow = await self._load_flow_for_swimlane(flow_id)
        await self._auto_generate_swimlane(flow)

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

    # ── Constraints ──────────────────────────────────────────────────────────

    async def create_constraint(self, project_id: uuid.UUID, body: ProjectConstraintCreate) -> ProjectConstraintResponse:
        obj = ProjectConstraint(project_id=project_id, type=body.type, description=body.description, severity=body.severity)
        self.db.add(obj)
        await self.db.flush()
        return ProjectConstraintResponse.model_validate(obj)

    async def list_constraints(self, project_id: uuid.UUID, type=None, severity=None) -> list[ProjectConstraintResponse]:
        q = select(ProjectConstraint).where(ProjectConstraint.project_id == project_id)
        if type is not None:
            q = q.where(ProjectConstraint.type == type)
        if severity is not None:
            q = q.where(ProjectConstraint.severity == severity)
        result = await self.db.execute(q.order_by(ProjectConstraint.created_at))
        return [ProjectConstraintResponse.model_validate(c) for c in result.scalars().all()]

    async def update_constraint(self, project_id: uuid.UUID, constraint_id: uuid.UUID, body: ProjectConstraintUpdate) -> ProjectConstraintResponse:
        result = await self.db.execute(
            select(ProjectConstraint).where(ProjectConstraint.id == constraint_id, ProjectConstraint.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy constraint")
        if body.type is not None:
            obj.type = body.type
        if body.description is not None:
            obj.description = body.description
        if body.severity is not None:
            obj.severity = body.severity
        return ProjectConstraintResponse.model_validate(obj)

    async def delete_constraint(self, project_id: uuid.UUID, constraint_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ProjectConstraint).where(ProjectConstraint.id == constraint_id, ProjectConstraint.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy constraint")
        await self.db.delete(obj)

    # ── Business Requirements ─────────────────────────────────────────────────

    async def create_business_requirement(self, project_id: uuid.UUID, body: ProjectBusinessRequirementCreate) -> ProjectBusinessRequirementResponse:
        obj = ProjectBusinessRequirement(
            project_id=project_id,
            description=body.description,
            priority=body.priority,
            is_critical=body.is_critical,
        )
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return ProjectBusinessRequirementResponse.model_validate(obj)

    async def list_business_requirements(self, project_id: uuid.UUID) -> list[ProjectBusinessRequirementResponse]:
        result = await self.db.execute(
            select(ProjectBusinessRequirement).where(ProjectBusinessRequirement.project_id == project_id).order_by(ProjectBusinessRequirement.created_at)
        )
        return [ProjectBusinessRequirementResponse.model_validate(r) for r in result.scalars().all()]

    async def update_business_requirement(self, project_id: uuid.UUID, br_id: uuid.UUID, body: ProjectBusinessRequirementUpdate) -> ProjectBusinessRequirementResponse:
        result = await self.db.execute(
            select(ProjectBusinessRequirement).where(ProjectBusinessRequirement.id == br_id, ProjectBusinessRequirement.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy business requirement")
        if body.description is not None:
            obj.description = body.description
        if body.priority is not None:
            obj.priority = body.priority
        if body.is_critical is not None:
            obj.is_critical = body.is_critical
        await self.db.flush()
        await self.db.refresh(obj)
        return ProjectBusinessRequirementResponse.model_validate(obj)

    async def delete_business_requirement(self, project_id: uuid.UUID, br_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(ProjectBusinessRequirement).where(ProjectBusinessRequirement.id == br_id, ProjectBusinessRequirement.project_id == project_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy business requirement")
        await self.db.delete(obj)
