import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from app.core.guards import require_project_access
from app.core.responses import ok
from app.deps import current_user, get_estimate_service
from app.models.user import User
from app.schemas.estimate import EstimateListResponse
from app.schemas.response import ApiResponse
from app.services.estimate_service import EstimateService, VALID_VALUES

router = APIRouter(prefix="/projects/{project_id}/stories/{story_id}/estimates", tags=["estimates"])


class EstimateIn(BaseModel):
    value: str

    @field_validator("value")
    @classmethod
    def check_value(cls, v: str) -> str:
        if v not in VALID_VALUES:
            raise ValueError(f"Giá trị phải là một trong: {sorted(VALID_VALUES)}")
        return v


@router.post("", response_model=ApiResponse[EstimateListResponse])
async def submit_estimate(
    project_id: uuid.UUID,
    story_id: uuid.UUID,
    body: EstimateIn,
    user: User = Depends(current_user),
    service: EstimateService = Depends(get_estimate_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.upsert(project_id, story_id, user.id, body.value))


@router.get("", response_model=ApiResponse[EstimateListResponse])
async def list_estimates(
    project_id: uuid.UUID,
    story_id: uuid.UUID,
    user: User = Depends(current_user),
    service: EstimateService = Depends(get_estimate_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id, story_id))
