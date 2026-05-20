"""github oauth connect: nullable installation_id, add connected_by_user_id

Revision ID: f42cfeea4180
Revises: a2b3c4d5e6f7
Create Date: 2026-05-18 23:28:35.872548

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f42cfeea4180'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('github_connections', sa.Column('connected_by_user_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_github_connections_connected_by_user_id', 'github_connections', 'users', ['connected_by_user_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_github_connections_connected_by_user_id', 'github_connections', type_='foreignkey')
    op.drop_column('github_connections', 'connected_by_user_id')
