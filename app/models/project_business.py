import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base


class RuleType(str, enum.Enum):
    constraint = "constraint"
    calculation = "calculation"
    validation = "validation"
    process = "process"
    policy = "policy"
    regulation = "regulation"


_rule_type = SAEnum(RuleType, name="ruletype")


class ProjectGoal(AuditMixin, Base):
    __tablename__ = "project_goals"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped["Project"] = relationship(back_populates="goals")  # noqa: F821


class ProjectFlow(AuditMixin, Base):
    __tablename__ = "project_flows"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped["Project"] = relationship(back_populates="flows")  # noqa: F821


class ProjectRule(AuditMixin, Base):
    __tablename__ = "project_rules"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_def: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[RuleType] = mapped_column(_rule_type, nullable=False)
    is_dynamic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="rules")  # noqa: F821
