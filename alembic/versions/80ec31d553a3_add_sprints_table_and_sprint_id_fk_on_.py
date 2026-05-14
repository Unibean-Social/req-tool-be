"""add sprints table and sprint_id fk on stories

Revision ID: 80ec31d553a3
Revises: f5cd7e21d92d
Create Date: 2026-05-14 21:51:52.660861

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '80ec31d553a3'
down_revision: Union[str, None] = 'f5cd7e21d92d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('sprints',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('goal', sa.Text(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('status', sa.Enum('planning', 'active', 'completed', 'cancelled', name='sprint_status'), nullable=False),
    sa.Column('github_milestone_number', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sprints_project_id'), 'sprints', ['project_id'], unique=False)
    # Add FK from stories.sprint_id to sprints.id
    with op.batch_alter_table('stories') as batch_op:
        batch_op.create_foreign_key('fk_stories_sprint_id', 'sprints', ['sprint_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('stories') as batch_op:
        batch_op.drop_constraint('fk_stories_sprint_id', type_='foreignkey')
    op.drop_index(op.f('ix_sprints_project_id'), table_name='sprints')
    op.drop_table('sprints')
