import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base
from app.models.requirements import Priority, _priority


class NFRCategory(str, enum.Enum):
    performance = "performance"
    security = "security"
    usability = "usability"
    reliability = "reliability"
    compliance = "compliance"
    maintainability = "maintainability"


class NFR(AuditMixin, Base):
    __tablename__ = "nfrs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[NFRCategory] = mapped_column(
        Enum(NFRCategory, name="nfrcategory"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[Priority] = mapped_column(_priority, nullable=False, default=Priority.medium)
    source_feature_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("features.id", ondelete="SET NULL"), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="nfrs")  # noqa: F821
    source_feature: Mapped["Feature"] = relationship()  # noqa: F821
