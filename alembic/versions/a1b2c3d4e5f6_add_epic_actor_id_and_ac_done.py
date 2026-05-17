"""add epic.actor_id fk and ac.done

Revision ID: a1b2c3d4e5f6
Revises: 81489e31ffc4
Create Date: 2026-05-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '81489e31ffc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable actor_id FK on epics (nullable to survive populated DBs)
    op.add_column('epics', sa.Column('actor_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index('ix_epics_actor_id', 'epics', ['actor_id'])
    op.create_foreign_key(
        'fk_epics_actor_id', 'epics', 'actors', ['actor_id'], ['id'], ondelete='SET NULL'
    )

    # Add done boolean on acceptance_criteria
    op.add_column(
        'acceptance_criteria',
        sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('acceptance_criteria', 'done')
    op.drop_constraint('fk_epics_actor_id', 'epics', type_='foreignkey')
    op.drop_index('ix_epics_actor_id', table_name='epics')
    op.drop_column('epics', 'actor_id')
