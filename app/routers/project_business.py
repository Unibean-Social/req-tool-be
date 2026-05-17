import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user, get_project_business_service
from app.models.actor import Actor
from app.models.nfr import NFR
from app.models.project_business import ProjectFlow, ProjectGoal, ProjectRule
from app.models.requirements import Epic
from app.models.stakeholder import Stakeholder
from app.models.user import User
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
from app.schemas.response import ApiResponse
from app.services.project_business_service import ProjectBusinessService

router = APIRouter(prefix="/projects/{project_id}", tags=["business-context"])


# ── Goals ─────────────────────────────────────────────────────────────────────

@router.post("/goals", response_model=ApiResponse[ProjectGoalResponse], status_code=status.HTTP_201_CREATED)
async def create_goal(
    project_id: uuid.UUID,
    body: ProjectGoalCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_goal(project_id, body))


@router.get("/goals", response_model=ApiResponse[list[ProjectGoalResponse]])
async def list_goals(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_goals(project_id))


@router.patch("/goals/{goal_id}", response_model=ApiResponse[ProjectGoalResponse])
async def update_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    body: ProjectGoalUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_goal(project_id, goal_id, body))


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_goal(project_id, goal_id)


# ── Flows ─────────────────────────────────────────────────────────────────────

@router.post("/flows", response_model=ApiResponse[ProjectFlowResponse], status_code=status.HTTP_201_CREATED)
async def create_flow(
    project_id: uuid.UUID,
    body: ProjectFlowCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_flow(project_id, body))


@router.get("/flows", response_model=ApiResponse[list[ProjectFlowResponse]])
async def list_flows(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_flows(project_id))


@router.patch("/flows/{flow_id}", response_model=ApiResponse[ProjectFlowResponse])
async def update_flow(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    body: ProjectFlowUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_flow(project_id, flow_id, body))


@router.delete("/flows/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_flow(project_id, flow_id)


# ── Rules ─────────────────────────────────────────────────────────────────────

@router.post("/rules", response_model=ApiResponse[ProjectRuleResponse], status_code=status.HTTP_201_CREATED)
async def create_rule(
    project_id: uuid.UUID,
    body: ProjectRuleCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_rule(project_id, body))


@router.get("/rules", response_model=ApiResponse[list[ProjectRuleResponse]])
async def list_rules(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_rules(project_id))


@router.patch("/rules/{rule_id}", response_model=ApiResponse[ProjectRuleResponse])
async def update_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    body: ProjectRuleUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_rule(project_id, rule_id, body))


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_rule(project_id, rule_id)


# ── Setup Progress ────────────────────────────────────────────────────────────

@router.get("/setup-progress")
async def get_setup_progress(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await require_project_access(project_id, user, db)

    has_stakeholders = (await db.scalar(
        select(func.count()).select_from(Stakeholder).where(Stakeholder.project_id == project_id)
    ) or 0) > 0
    has_goals = (await db.scalar(
        select(func.count()).select_from(ProjectGoal).where(ProjectGoal.project_id == project_id)
    ) or 0) > 0
    has_flows = (await db.scalar(
        select(func.count()).select_from(ProjectFlow).where(ProjectFlow.project_id == project_id)
    ) or 0) > 0
    has_rules = (await db.scalar(
        select(func.count()).select_from(ProjectRule).where(ProjectRule.project_id == project_id)
    ) or 0) > 0
    has_nfrs = (await db.scalar(
        select(func.count()).select_from(NFR).where(NFR.project_id == project_id)
    ) or 0) > 0
    has_requirements = (await db.scalar(
        select(func.count()).select_from(Actor).where(Actor.project_id == project_id)
    ) or 0) > 0

    core_complete = bool(project.context and project.description and project.problems)

    return ok({
        "core": core_complete,
        "stakeholders": has_stakeholders,
        "goals": has_goals,
        "flows": has_flows,
        "rules": has_rules,
        "nfrs": has_nfrs,
        "requirements": has_requirements,
    })
