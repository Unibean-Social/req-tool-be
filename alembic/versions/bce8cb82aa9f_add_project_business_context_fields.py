"""add project business context fields

Revision ID: bce8cb82aa9f
Revises: 80ec31d553a3
Create Date: 2026-05-15 11:18:27.783435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bce8cb82aa9f'
down_revision: Union[str, None] = '80ec31d553a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('context', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('problems', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('stakeholders', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('business_goals', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('business_flows', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('business_rules', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('proposed_solutions', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'proposed_solutions')
    op.drop_column('projects', 'business_rules')
    op.drop_column('projects', 'business_flows')
    op.drop_column('projects', 'business_goals')
    op.drop_column('projects', 'stakeholders')
    op.drop_column('projects', 'problems')
    op.drop_column('projects', 'context')
