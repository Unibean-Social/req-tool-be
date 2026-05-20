import uuid

from fastapi import APIRouter, Depends, Query
from fastapi import status as http_status

from app.core.guards import require_project_access
from app.core.responses import ok
from app.deps import current_user, get_sync_service
from app.models.requirements import ItemType
from app.models.sync import SyncLogStatus
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.sync import PushReport, PushResultItem, StageRequest, SyncLogResponse, SyncQueueResponse
from app.services.sync_service import SyncService

router = APIRouter(tags=["Sync"])


@router.post(
    "/projects/{project_id}/sync/stage",
    response_model=ApiResponse[list[SyncQueueResponse]],
    status_code=http_status.HTTP_200_OK,
)
async def stage_items(
    project_id: uuid.UUID,
    body: StageRequest,
    user: User = Depends(current_user),
    service: SyncService = Depends(get_sync_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.stage_items(project_id, body))


@router.get(
    "/projects/{project_id}/sync/pending",
    response_model=ApiResponse[list[SyncQueueResponse]],
)
async def get_pending(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SyncService = Depends(get_sync_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_pending(project_id))


@router.delete(
    "/projects/{project_id}/sync/pending/{queue_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def unstage_item(
    project_id: uuid.UUID,
    queue_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SyncService = Depends(get_sync_service),
):
    await require_project_access(project_id, user, service.db)
    await service.unstage_item(project_id, queue_id)


@router.post(
    "/projects/{project_id}/sync/push",
    response_model=ApiResponse[PushReport],
)
async def push_items(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SyncService = Depends(get_sync_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.push_items(project_id))


@router.get(
    "/projects/{project_id}/sync/logs",
    response_model=ApiResponse[list[SyncLogResponse]],
)
async def get_logs(
    project_id: uuid.UUID,
    item_id: uuid.UUID | None = Query(None),
    status: SyncLogStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    service: SyncService = Depends(get_sync_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_logs(project_id, item_id, status, limit, offset))


@router.post(
    "/projects/{project_id}/sync/repush/{item_type}/{item_id}",
    response_model=ApiResponse[PushResultItem],
)
async def repush_item(
    project_id: uuid.UUID,
    item_type: ItemType,
    item_id: uuid.UUID,
    user: User = Depends(current_user),
    service: SyncService = Depends(get_sync_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.repush_item(project_id, item_type, item_id))
