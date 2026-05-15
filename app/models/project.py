import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text
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
    stakeholders: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)
    business_goals: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)
    business_flows: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)
    business_rules: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)
    proposed_solutions: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="projects")  # noqa: F821
    actors: Mapped[list["Actor"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # noqa: F821
    github_connection: Mapped["GithubConnection | None"] = relationship(back_populates="project", uselist=False)  # noqa: F821
    epics: Mapped[list["Epic"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # noqa: F821
    sprints: Mapped[list["Sprint"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # noqa: F821
