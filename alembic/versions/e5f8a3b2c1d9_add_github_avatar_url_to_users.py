"""add github_avatar_url to users

Revision ID: e5f8a3b2c1d9
Revises: d4e7f1a2b3c5
Create Date: 2026-05-14

"""
from alembic import op
import sqlalchemy as sa

revision = "e5f8a3b2c1d9"
down_revision = "d4e7f1a2b3c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("github_avatar_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "github_avatar_url")
