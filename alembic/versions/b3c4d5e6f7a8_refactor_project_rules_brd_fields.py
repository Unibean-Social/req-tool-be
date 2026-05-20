"""refactor project_rules: rename description→rule_def, drop linked_feature_id, add type/is_dynamic/source

Revision ID: b3c4d5e6f7a8
Revises: f42cfeea4180
Create Date: 2026-05-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "f42cfeea4180"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # a) Create ruletype enum
    conn.execute(sa.text(
        "CREATE TYPE ruletype AS ENUM "
        "('constraint', 'calculation', 'validation', 'process', 'policy', 'regulation')"
    ))

    # b) Rename description → rule_def
    op.alter_column("project_rules", "description", new_column_name="rule_def")

    # c) Drop FK constraint + column for linked_feature_id
    op.drop_constraint("project_rules_linked_feature_id_fkey", "project_rules", type_="foreignkey")
    op.drop_column("project_rules", "linked_feature_id")

    # d) Add new BRD fields
    op.add_column("project_rules", sa.Column(
        "type",
        postgresql.ENUM(name="ruletype", create_type=False),
        nullable=False,
        server_default="constraint",
    ))
    op.add_column("project_rules", sa.Column(
        "is_dynamic",
        sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    ))
    op.add_column("project_rules", sa.Column(
        "source",
        sa.Text(),
        nullable=True,
    ))

    # e) Remove server defaults now that schema is stable (optional hygiene)
    op.alter_column("project_rules", "type", server_default=None)
    op.alter_column("project_rules", "is_dynamic", server_default=None)


def downgrade() -> None:
    # Reverse order

    # a) Drop new columns
    op.drop_column("project_rules", "source")
    op.drop_column("project_rules", "is_dynamic")
    op.drop_column("project_rules", "type")

    # b) Restore linked_feature_id
    op.add_column("project_rules", sa.Column(
        "linked_feature_id",
        postgresql.UUID(as_uuid=True),
        nullable=True,
    ))
    op.create_foreign_key(
        "project_rules_linked_feature_id_fkey",
        "project_rules",
        "features",
        ["linked_feature_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # c) Rename rule_def → description
    op.alter_column("project_rules", "rule_def", new_column_name="description")

    # d) Drop enum
    sa.Enum(name="ruletype").drop(op.get_bind())
