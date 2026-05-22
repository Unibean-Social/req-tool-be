"""add code to project_rules

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-05-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project_rules", sa.Column("code", sa.Text(), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE project_rules
        SET code = 'BR-' || LPAD(rn::text, 3, '0')
        FROM (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY created_at) AS rn
            FROM project_rules
        ) sub
        WHERE project_rules.id = sub.id
    """))

    op.alter_column("project_rules", "code", nullable=False)
    op.create_unique_constraint("uq_project_rules_project_code", "project_rules", ["project_id", "code"])


def downgrade() -> None:
    op.drop_constraint("uq_project_rules_project_code", "project_rules", type_="unique")
    op.drop_column("project_rules", "code")
