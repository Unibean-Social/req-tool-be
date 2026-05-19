import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user, get_brd_export_service, get_project_business_service, get_staleness_service
from app.schemas.staleness import StalenessWarningItem
from app.services.staleness_service import StalenessService
from app.models.actor import Actor
from app.models.nfr import NFR
from app.models.project_business import (
    ConstraintSeverity,
    ConstraintType,
    ProjectConstraint,
    ProjectFlow,
    ProjectFlowAction,
    ProjectGoal,
    ProjectRule,
)
from app.models.stakeholder import Stakeholder
from app.models.user import User
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
    ProjectGoalObjectiveCreate,
    ProjectGoalObjectiveResponse,
    ProjectGoalObjectiveUpdate,
    ProjectGoalResponse,
    ProjectGoalUpdate,
    ProjectRuleCreate,
    ProjectRuleResponse,
    ProjectRuleUpdate,
    SwimlaneRequest,
)
from app.schemas.response import ApiResponse
from app.services.brd_export_service import BRDExportService
from app.services.project_business_service import ProjectBusinessService

router = APIRouter(prefix="/projects/{project_id}")


# ── Goals ─────────────────────────────────────────────────────────────────────

@router.post("/goals", response_model=ApiResponse[ProjectGoalResponse], status_code=status.HTTP_201_CREATED, tags=["Project Goals"])
async def create_goal(
    project_id: uuid.UUID,
    body: ProjectGoalCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_goal(project_id, body))


@router.get("/goals", response_model=ApiResponse[list[ProjectGoalResponse]], tags=["Project Goals"])
async def list_goals(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_goals(project_id))


@router.patch("/goals/{goal_id}", response_model=ApiResponse[ProjectGoalResponse], tags=["Project Goals"])
async def update_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    body: ProjectGoalUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_goal(project_id, goal_id, body))


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Project Goals"])
async def delete_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_goal(project_id, goal_id)


# ── Flows ─────────────────────────────────────────────────────────────────────

@router.post("/flows", response_model=ApiResponse[ProjectFlowDetailResponse], status_code=status.HTTP_201_CREATED, tags=["Project Flows"])
async def create_flow(
    project_id: uuid.UUID,
    body: ProjectFlowCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_flow(project_id, body))


@router.get("/flows", response_model=ApiResponse[list[ProjectFlowResponse]], tags=["Project Flows"])
async def list_flows(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_flows(project_id))


@router.patch("/flows/{flow_id}", response_model=ApiResponse[ProjectFlowResponse], tags=["Project Flows"])
async def update_flow(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    body: ProjectFlowUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_flow(project_id, flow_id, body))


@router.delete("/flows/{flow_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Project Flows"])
async def delete_flow(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_flow(project_id, flow_id)


@router.get("/flows/{flow_id}", response_model=ApiResponse[ProjectFlowDetailResponse], tags=["Project Flows"])
async def get_flow(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_flow(project_id, flow_id))


@router.put("/flows/{flow_id}/swimlane", response_model=ApiResponse[ProjectFlowDetailResponse], tags=["Project Flows"])
async def update_flow_swimlane(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    body: SwimlaneRequest,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_swimlane(project_id, flow_id, body))


# ── Flow Actions ──────────────────────────────────────────────────────────────

@router.post("/flows/{flow_id}/actions", response_model=ApiResponse[list[ProjectFlowActionResponse]], status_code=status.HTTP_201_CREATED, tags=["Flow Actions"])
async def create_flow_actions(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    body: list[ProjectFlowActionCreate],
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_flow_actions(project_id, flow_id, body))


@router.patch("/flows/{flow_id}/actions", response_model=ApiResponse[list[ProjectFlowActionResponse]], tags=["Flow Actions"])
async def update_flow_actions(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    body: list[ProjectFlowActionUpdate],
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_flow_actions(project_id, flow_id, body))


@router.delete("/flows/{flow_id}/actions/{action_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Flow Actions"])
async def delete_flow_action(
    project_id: uuid.UUID,
    flow_id: uuid.UUID,
    action_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_flow_action(project_id, flow_id, action_id)



# ── Rules ─────────────────────────────────────────────────────────────────────

@router.post("/rules", response_model=ApiResponse[ProjectRuleResponse], status_code=status.HTTP_201_CREATED, tags=["Business Rules"])
async def create_rule(
    project_id: uuid.UUID,
    body: ProjectRuleCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_rule(project_id, body))


@router.get("/rules", response_model=ApiResponse[list[ProjectRuleResponse]], tags=["Business Rules"])
async def list_rules(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_rules(project_id))


@router.patch("/rules/{rule_id}", response_model=ApiResponse[ProjectRuleResponse], tags=["Business Rules"])
async def update_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    body: ProjectRuleUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_rule(project_id, rule_id, body))


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Business Rules"])
async def delete_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_rule(project_id, rule_id)


# ── Goal Objectives ───────────────────────────────────────────────────────────

@router.post("/goals/{goal_id}/objectives", response_model=ApiResponse[ProjectGoalObjectiveResponse], status_code=status.HTTP_201_CREATED, tags=["Goal Objectives"])
async def create_objective(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    body: ProjectGoalObjectiveCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_objective(project_id, goal_id, body))


@router.get("/goals/{goal_id}/objectives", response_model=ApiResponse[list[ProjectGoalObjectiveResponse]], tags=["Goal Objectives"])
async def list_objectives(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_objectives(project_id, goal_id))


@router.patch("/goals/{goal_id}/objectives/{objective_id}", response_model=ApiResponse[ProjectGoalObjectiveResponse], tags=["Goal Objectives"])
async def update_objective(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    objective_id: uuid.UUID,
    body: ProjectGoalObjectiveUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_objective(project_id, goal_id, objective_id, body))


@router.delete("/goals/{goal_id}/objectives/{objective_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Goal Objectives"])
async def delete_objective(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    objective_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_objective(project_id, goal_id, objective_id)


# ── Constraints ───────────────────────────────────────────────────────────────

@router.post("/constraints", response_model=ApiResponse[ProjectConstraintResponse], status_code=status.HTTP_201_CREATED, tags=["Project Constraints"])
async def create_constraint(
    project_id: uuid.UUID,
    body: ProjectConstraintCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_constraint(project_id, body))


@router.get("/constraints", response_model=ApiResponse[list[ProjectConstraintResponse]], tags=["Project Constraints"])
async def list_constraints(
    project_id: uuid.UUID,
    type: ConstraintType | None = Query(None),
    severity: ConstraintSeverity | None = Query(None),
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_constraints(project_id, type, severity))


@router.patch("/constraints/{constraint_id}", response_model=ApiResponse[ProjectConstraintResponse], tags=["Project Constraints"])
async def update_constraint(
    project_id: uuid.UUID,
    constraint_id: uuid.UUID,
    body: ProjectConstraintUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_constraint(project_id, constraint_id, body))


@router.delete("/constraints/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Project Constraints"])
async def delete_constraint(
    project_id: uuid.UUID,
    constraint_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_constraint(project_id, constraint_id)


# ── Business Requirements ─────────────────────────────────────────────────────

@router.post("/business-requirements", response_model=ApiResponse[ProjectBusinessRequirementResponse], status_code=status.HTTP_201_CREATED, tags=["Business Requirements"])
async def create_business_requirement(
    project_id: uuid.UUID,
    body: ProjectBusinessRequirementCreate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create_business_requirement(project_id, body))


@router.get("/business-requirements", response_model=ApiResponse[list[ProjectBusinessRequirementResponse]], tags=["Business Requirements"])
async def list_business_requirements(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_business_requirements(project_id))


@router.patch("/business-requirements/{br_id}", response_model=ApiResponse[ProjectBusinessRequirementResponse], tags=["Business Requirements"])
async def update_business_requirement(
    project_id: uuid.UUID,
    br_id: uuid.UUID,
    body: ProjectBusinessRequirementUpdate,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update_business_requirement(project_id, br_id, body))


@router.delete("/business-requirements/{br_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Business Requirements"])
async def delete_business_requirement(
    project_id: uuid.UUID,
    br_id: uuid.UUID,
    user: User = Depends(current_user),
    service: ProjectBusinessService = Depends(get_project_business_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete_business_requirement(project_id, br_id)


# ── Setup Progress ────────────────────────────────────────────────────────────

@router.get("/setup-progress", tags=["Project Setup"])
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
    has_actors = (await db.scalar(
        select(func.count()).select_from(Actor).where(Actor.project_id == project_id)
    ) or 0) > 0
    has_constraints = (await db.scalar(
        select(func.count()).select_from(ProjectConstraint).where(ProjectConstraint.project_id == project_id)
    ) or 0) > 0

    core_complete = bool(project.context and project.description and project.problems)

    return ok({
        "core": core_complete,
        "business_requirements": {
            "stakeholders": has_stakeholders,
            "goals": has_goals,
            "flows": has_flows,
            "rules": has_rules,
            "constraints": has_constraints,
        },
        "user_requirements": {
            "nfrs": has_nfrs,
        },
        "functional_requirements": {
            "actors": has_actors,
        },
    })


# ── BRD Export ────────────────────────────────────────────────────────────────

@router.get("/brd/export", tags=["BRD"])
async def export_brd(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: BRDExportService = Depends(get_brd_export_service),
):
    await require_project_access(project_id, user, service.db)
    from fastapi.responses import Response
    md = await service.generate(project_id)
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="brd-{project_id}.md"'},
    )


@router.get("/staleness-warnings", response_model=ApiResponse[list[StalenessWarningItem]], tags=["Project Setup"])
async def get_staleness_warnings(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: StalenessService = Depends(get_staleness_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_stale_items(project_id))
