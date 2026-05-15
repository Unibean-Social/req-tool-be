import uuid

from fastapi import APIRouter, Depends, status

from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_epic_service
from app.models.user import User
from app.schemas.requirements import (
    CloseRequest,
    CloseReasonResponse,
    EpicCreateRequest,
    EpicResponse,
    EpicTree,
    EpicUpdateRequest,
)
from app.schemas.response import ApiResponse
from app.services.requirements.epic_service import EpicService

router = APIRouter(prefix="/projects/{project_id}", tags=["epics"])


@router.post("/epics", response_model=ApiResponse[EpicResponse], status_code=status.HTTP_201_CREATED)
async def create_epic(
    project_id: uuid.UUID,
    body: EpicCreateRequest,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.create(project_id, body, user))


@router.get("/epics", response_model=ApiResponse[list[EpicResponse]])
async def list_epics(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id))


@router.get("/epics/{epic_id}", response_model=ApiResponse[EpicResponse])
async def get_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get(project_id, epic_id))


@router.patch("/epics/{epic_id}", response_model=ApiResponse[EpicResponse])
async def update_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    body: EpicUpdateRequest,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.update(project_id, epic_id, body))


@router.delete("/epics/{epic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    await service.delete(project_id, epic_id)


@router.patch("/epics/{epic_id}/close", response_model=ApiResponse[CloseReasonResponse])
async def close_epic(
    project_id: uuid.UUID,
    epic_id: uuid.UUID,
    body: CloseRequest,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.close(project_id, epic_id, body, user))


@router.get("/requirements/tree", response_model=ApiResponse[list[EpicTree]])
async def get_requirements_tree(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_tree(project_id))
