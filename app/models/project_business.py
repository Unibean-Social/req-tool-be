import enum
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Table, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import JSON
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


# M2M association table — ProjectFlowAction ↔ ProjectRule
project_flow_action_rules = Table(
    "project_flow_action_rules",
    Base.metadata,
    Column("action_id", UUID(as_uuid=True),
           ForeignKey("project_flow_actions.id", ondelete="CASCADE"), primary_key=True),
    Column("rule_id", UUID(as_uuid=True),
           ForeignKey("project_rules.id", ondelete="CASCADE"), primary_key=True),
)


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
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_project_flows_project_code"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    swimlane: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    project: Mapped["Project"] = relationship(back_populates="flows")  # noqa: F821
    actions: Mapped[list["ProjectFlowAction"]] = relationship(
        back_populates="flow",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ProjectFlowAction.order",
    )


class ProjectFlowAction(AuditMixin, Base):
    __tablename__ = "project_flow_actions"

    flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_flows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stakeholders.id", ondelete="SET NULL"), nullable=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    flow: Mapped["ProjectFlow"] = relationship(back_populates="actions")
    actor: Mapped["Stakeholder | None"] = relationship()  # noqa: F821
    rules: Mapped[list["ProjectRule"]] = relationship(
        secondary="project_flow_action_rules",
        back_populates="flow_actions",
        lazy="selectin",
    )


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
    flow_actions: Mapped[list["ProjectFlowAction"]] = relationship(
        secondary="project_flow_action_rules",
        back_populates="rules",
        lazy="noload",
    )
