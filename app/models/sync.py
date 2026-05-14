import enum
import uuid
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import AuditMixin, Base
from app.models.requirements import ItemType, _item_type


class SyncOperation(str, enum.Enum):
    create = "create"
    update = "update"
    close = "close"


class SyncQueueStatus(str, enum.Enum):
    pending = "pending"
    failed = "failed"


class SyncLogStatus(str, enum.Enum):
    success = "success"
    failed = "failed"


_sync_operation = SAEnum(SyncOperation, name="sync_operation")
_sync_queue_status = SAEnum(SyncQueueStatus, name="sync_queue_status")
_sync_log_status = SAEnum(SyncLogStatus, name="sync_log_status")


class SyncQueue(AuditMixin, Base):
    __tablename__ = "sync_queue"
    __table_args__ = (UniqueConstraint("project_id", "item_type", "item_id", name="uq_sync_queue_item"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_type: Mapped[ItemType] = mapped_column(_item_type, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operation: Mapped[SyncOperation] = mapped_column(_sync_operation, nullable=False)
    body_snapshot: Mapped[Any] = mapped_column(JSON, nullable=False)
    status: Mapped[SyncQueueStatus] = mapped_column(
        _sync_queue_status, nullable=False, default=SyncQueueStatus.pending
    )


class GithubItem(AuditMixin, Base):
    __tablename__ = "github_items"
    __table_args__ = (UniqueConstraint("item_type", "item_id", name="uq_github_item"),)

    item_type: Mapped[ItemType] = mapped_column(_item_type, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    github_issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    github_issue_url: Mapped[str] = mapped_column(Text, nullable=False)


class SyncLog(AuditMixin, Base):
    __tablename__ = "sync_logs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sync_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sync_queue.id", ondelete="SET NULL"), nullable=True
    )
    item_type: Mapped[ItemType] = mapped_column(_item_type, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    operation: Mapped[SyncOperation] = mapped_column(_sync_operation, nullable=False)
    status: Mapped[SyncLogStatus] = mapped_column(_sync_log_status, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_issue_url: Mapped[str | None] = mapped_column(Text, nullable=True)
