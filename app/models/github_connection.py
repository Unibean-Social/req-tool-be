import uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base, AuditMixin


class GithubConnection(AuditMixin, Base):
    __tablename__ = "github_connections"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    repo_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(255), nullable=False)
    installation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Stored Fernet-encrypted; use app.core.crypto to read/write
    access_token: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # not_started | in_progress | completed
    bootstrap_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_started")
    # manual | auto_push
    sync_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # Fernet-encrypted webhook secret
    webhook_secret: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="github_connection")  # noqa: F821
