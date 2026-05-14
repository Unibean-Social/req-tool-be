import enum
import uuid
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import AuditMixin, Base


class ItemStatus(str, enum.Enum):
    draft = "draft"
    in_progress = "in_progress"
    done = "done"
    rejected = "rejected"
    duplicate = "duplicate"
    wont_fix = "wont_fix"
    deferred = "deferred"


TERMINAL_STATUSES = {
    ItemStatus.done,
    ItemStatus.rejected,
    ItemStatus.duplicate,
    ItemStatus.wont_fix,
    ItemStatus.deferred,
}

NON_TERMINAL_STATUSES = {ItemStatus.draft, ItemStatus.in_progress}


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class CloseReasonEnum(str, enum.Enum):
    done = "done"
    rejected = "rejected"
    duplicate = "duplicate"
    wont_fix = "wont_fix"
    deferred = "deferred"


class ItemType(str, enum.Enum):
    epic = "epic"
    feature = "feature"
    story = "story"
    task = "task"


_item_status = SAEnum(ItemStatus, name="item_status")
_priority = SAEnum(Priority, name="priority")
_close_reason_enum = SAEnum(CloseReasonEnum, name="close_reason_enum")
_item_type = SAEnum(ItemType, name="item_type")


class Epic(AuditMixin, Base):
    __tablename__ = "epics"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ItemStatus] = mapped_column(_item_status, nullable=False, default=ItemStatus.draft)
    priority: Mapped[Priority] = mapped_column(_priority, nullable=False, default=Priority.medium)
    labels: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)

    project: Mapped["Project"] = relationship(back_populates="epics")  # noqa: F821
    features: Mapped[list["Feature"]] = relationship(back_populates="epic", cascade="all, delete-orphan")


class Feature(AuditMixin, Base):
    __tablename__ = "features"

    epic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("epics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prefix: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ItemStatus] = mapped_column(_item_status, nullable=False, default=ItemStatus.draft)
    priority: Mapped[Priority] = mapped_column(_priority, nullable=False, default=Priority.medium)
    labels: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)

    epic: Mapped["Epic"] = relationship(back_populates="features")
    stories: Mapped[list["Story"]] = relationship(back_populates="feature", cascade="all, delete-orphan")


class Story(AuditMixin, Base):
    __tablename__ = "stories"

    feature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("features.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prefix: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ItemStatus] = mapped_column(_item_status, nullable=False, default=ItemStatus.draft)
    priority: Mapped[Priority] = mapped_column(_priority, nullable=False, default=Priority.medium)
    labels: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)

    feature: Mapped["Feature"] = relationship(back_populates="stories")
    tasks: Mapped[list["Task"]] = relationship(back_populates="story", cascade="all, delete-orphan")
    acceptance_criteria: Mapped[list["AcceptanceCriteria"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="AcceptanceCriteria.order",
    )


class Task(AuditMixin, Base):
    __tablename__ = "tasks"

    story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prefix: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ItemStatus] = mapped_column(_item_status, nullable=False, default=ItemStatus.draft)
    priority: Mapped[Priority] = mapped_column(_priority, nullable=False, default=Priority.medium)
    labels: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)

    story: Mapped["Story"] = relationship(back_populates="tasks")


class AcceptanceCriteria(AuditMixin, Base):
    __tablename__ = "acceptance_criteria"

    story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    story: Mapped["Story"] = relationship(back_populates="acceptance_criteria")


class CloseReason(AuditMixin, Base):
    __tablename__ = "close_reasons"

    item_type: Mapped[ItemType] = mapped_column(_item_type, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    reason: Mapped[CloseReasonEnum] = mapped_column(_close_reason_enum, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    closed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
