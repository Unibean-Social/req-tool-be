import uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import JSON
from app.models.base import Base, AuditMixin


class Actor(AuditMixin, Base):
    __tablename__ = "actors"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    canvas_layout: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="actors")  # noqa: F821
