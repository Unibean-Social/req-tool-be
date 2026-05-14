"""add enrichment fields to story task github_connection

Revision ID: f5cd7e21d92d
Revises: d4e7f1a2b3c5
Create Date: 2026-05-14 21:49:27.984423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f5cd7e21d92d'
down_revision: Union[str, None] = 'd4e7f1a2b3c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('github_connections', sa.Column('sync_mode', sa.String(length=20), nullable=False, server_default='manual'))
    op.add_column('github_connections', sa.Column('webhook_secret', sa.String(length=1024), nullable=True))
    op.add_column('stories', sa.Column('story_points', sa.Integer(), nullable=True))
    op.add_column('stories', sa.Column('sprint_id', sa.UUID(), nullable=True))
    op.add_column('tasks', sa.Column('assignee_id', sa.UUID(), nullable=True))
    op.add_column('tasks', sa.Column('category', sa.String(length=50), nullable=True))
    op.add_column('tasks', sa.Column('estimated_hours', sa.Float(), nullable=True))
    op.create_foreign_key('fk_tasks_assignee_id', 'tasks', 'users', ['assignee_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_tasks_assignee_id', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'estimated_hours')
    op.drop_column('tasks', 'category')
    op.drop_column('tasks', 'assignee_id')
    op.drop_column('stories', 'sprint_id')
    op.drop_column('stories', 'story_points')
    op.drop_column('github_connections', 'webhook_secret')
    op.drop_column('github_connections', 'sync_mode')
