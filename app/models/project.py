import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import AuditMixin, Base


class Project(AuditMixin, Base):
    __tablename__ = "projects"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    problems: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)
    proposed_solutions: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    roi_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="projects")  # noqa: F821
    actors: Mapped[list["Actor"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # noqa: F821
    github_connection: Mapped["GithubConnection | None"] = relationship(back_populates="project", uselist=False)  # noqa: F821
    epics: Mapped[list["Epic"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # noqa: F821
    stakeholders: Mapped[list["Stakeholder"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # noqa: F821
    goals: Mapped[list["ProjectGoal"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="ProjectGoal.order")  # noqa: F821
    flows: Mapped[list["ProjectFlow"]] = relationship(back_populates="project", cascade="all, delete-orphan", passive_deletes=True)  # noqa: F821
    rules: Mapped[list["ProjectRule"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # noqa: F821
    nfrs: Mapped[list["NFR"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # noqa: F821
    constraints: Mapped[list["ProjectConstraint"]] = relationship(back_populates="project", cascade="all, delete-orphan", passive_deletes=True)  # noqa: F821
    business_requirements: Mapped[list["ProjectBusinessRequirement"]] = relationship(back_populates="project", cascade="all, delete-orphan", passive_deletes=True)  # noqa: F821
    out_of_scope_items: Mapped[list["ProjectOutOfScope"]] = relationship(back_populates="project", cascade="all, delete-orphan", passive_deletes=True, order_by="ProjectOutOfScope.order")  # noqa: F821
