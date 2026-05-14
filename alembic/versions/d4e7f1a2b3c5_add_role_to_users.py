"""add role to users

Revision ID: d4e7f1a2b3c5
Revises: c7e2f4a8b931
Create Date: 2026-05-14

"""
from alembic import op
import sqlalchemy as sa

revision = "d4e7f1a2b3c5"
down_revision = "c7e2f4a8b931"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="user"))


def downgrade() -> None:
    op.drop_column("users", "role")
