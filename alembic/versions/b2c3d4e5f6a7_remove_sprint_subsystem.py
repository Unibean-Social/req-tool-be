"""remove sprint subsystem

Sprint management is process/delivery tooling, not requirements capture.
One-way migration: sprint data is NOT recoverable after downgrade.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop sprint_id FK and column from stories
    op.drop_constraint('fk_stories_sprint_id', 'stories', type_='foreignkey')
    op.drop_column('stories', 'sprint_id')

    # Drop sprints table
    op.drop_index(op.f('ix_sprints_project_id'), table_name='sprints')
    op.drop_table('sprints')
    op.execute("DROP TYPE IF EXISTS sprint_status")


def downgrade() -> None:
    # Restore sprints table
    op.create_table(
        'sprints',
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('planning', 'active', 'completed', 'cancelled', name='sprint_status'),
            nullable=False,
            server_default='planning',
        ),
        sa.Column('github_milestone_number', sa.Integer(), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sprints_project_id'), 'sprints', ['project_id'], unique=False)

    # Restore sprint_id column on stories (data is lost — downgrade is structural only)
    op.add_column('stories', sa.Column('sprint_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_stories_sprint_id', 'stories', 'sprints', ['sprint_id'], ['id'], ondelete='SET NULL'
    )
