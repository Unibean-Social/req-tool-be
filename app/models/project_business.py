import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, Numeric, Table, Text, UniqueConstraint
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


class GoalPriority(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ConstraintType(str, enum.Enum):
    budget = "budget"
    timeline = "timeline"
    technical = "technical"
    resource = "resource"
    regulatory = "regulatory"
    risk = "risk"


class ConstraintSeverity(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class OutOfScopeCategory(str, enum.Enum):
    feature = "feature"
    integration = "integration"
    user_group = "user_group"
    process = "process"
    technical = "technical"


_rule_type = SAEnum(RuleType, name="ruletype")
_goal_priority = SAEnum(GoalPriority, name="goalpriority", native_enum=False)
_constraint_type = SAEnum(ConstraintType, name="constrainttype", native_enum=False)
_constraint_severity = SAEnum(ConstraintSeverity, name="constraintseverity", native_enum=False)
_out_of_scope_category = SAEnum(OutOfScopeCategory, name="outofscopecategory", native_enum=False)


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
    priority: Mapped[GoalPriority] = mapped_column(_goal_priority, nullable=False, default=GoalPriority.medium)
    success_metric: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="goals")  # noqa: F821
    objectives: Mapped[list["ProjectGoalObjective"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan", passive_deletes=True
    )


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
    code: Mapped[str] = mapped_column(Text, nullable=False)
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


class ProjectConstraint(AuditMixin, Base):
    __tablename__ = "project_constraints"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[ConstraintType] = mapped_column(_constraint_type, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[ConstraintSeverity] = mapped_column(_constraint_severity, nullable=False, default=ConstraintSeverity.medium)

    project: Mapped["Project"] = relationship(back_populates="constraints")  # noqa: F821


class ProjectGoalObjective(AuditMixin, Base):
    __tablename__ = "project_goal_objectives"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    goal: Mapped["ProjectGoal"] = relationship(back_populates="objectives")


class ProjectBusinessRequirement(AuditMixin, Base):
    __tablename__ = "project_business_requirements"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[GoalPriority] = mapped_column(_goal_priority, nullable=False, default=GoalPriority.medium)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    project: Mapped["Project"] = relationship(back_populates="business_requirements")  # noqa: F821


class ProjectOutOfScope(AuditMixin, Base):
    __tablename__ = "project_out_of_scope"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[OutOfScopeCategory | None] = mapped_column(_out_of_scope_category, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped["Project"] = relationship(back_populates="out_of_scope_items")  # noqa: F821
