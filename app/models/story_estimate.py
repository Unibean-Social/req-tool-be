import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base


class StoryEstimate(AuditMixin, Base):
    __tablename__ = "story_estimates"
    __table_args__ = (UniqueConstraint("story_id", "voter_id", name="uq_story_estimates_story_voter"),)

    story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[str] = mapped_column(String(4), nullable=False)

    story: Mapped["Story"] = relationship()  # noqa: F821
    voter: Mapped["User"] = relationship()  # noqa: F821
