import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import AuditMixin, Base


class ProjectContextDiagram(AuditMixin, Base):
    __tablename__ = "project_context_diagrams"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    stakeholder_ids: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    flows: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    layout: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    sync_meta: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="context_diagram")  # noqa: F821
