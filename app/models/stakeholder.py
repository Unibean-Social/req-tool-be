import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base


class InfluenceLevel(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Stakeholder(AuditMixin, Base):
    __tablename__ = "stakeholders"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_area: Mapped[str | None] = mapped_column(Text, nullable=True)
    influence_level: Mapped[InfluenceLevel] = mapped_column(
        Enum(InfluenceLevel, name="influencelevel"), nullable=False, default=InfluenceLevel.medium
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_business_actor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    project: Mapped["Project"] = relationship(back_populates="stakeholders")  # noqa: F821
