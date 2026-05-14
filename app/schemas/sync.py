import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.requirements import ItemType
from app.models.sync import SyncLogStatus, SyncOperation, SyncQueueStatus


class StageItem(BaseModel):
    item_type: ItemType
    item_id: uuid.UUID


class StageRequest(BaseModel):
    items: list[StageItem]


class SyncQueueResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    item_type: ItemType
    item_id: uuid.UUID
    operation: SyncOperation
    body_snapshot: dict[str, Any]
    status: SyncQueueStatus
    created_at: datetime
    updated_at: datetime


class SyncLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    sync_queue_id: uuid.UUID | None
    item_type: ItemType
    item_id: uuid.UUID
    operation: SyncOperation
    status: SyncLogStatus
    error_code: str | None
    error_message: str | None
    github_issue_number: int | None
    github_issue_url: str | None
    created_at: datetime


class GithubItemResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    item_type: ItemType
    item_id: uuid.UUID
    github_issue_number: int
    github_issue_url: str


class PushResultItem(BaseModel):
    item_type: ItemType
    item_id: uuid.UUID
    github_issue_number: int | None
    github_issue_url: str | None
    error_code: str | None
    error_message: str | None


class PushReport(BaseModel):
    pushed: list[PushResultItem]
    failed: list[PushResultItem]
