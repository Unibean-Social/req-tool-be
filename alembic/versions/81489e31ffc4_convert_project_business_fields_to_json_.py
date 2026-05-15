"""convert_project_business_fields_to_json_arrays

Revision ID: 81489e31ffc4
Revises: bce8cb82aa9f
Create Date: 2026-05-15 12:36:17.659122

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '81489e31ffc4'
down_revision: Union[str, None] = 'bce8cb82aa9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FIELDS = ["problems", "stakeholders", "business_goals", "business_flows", "business_rules", "proposed_solutions"]


def upgrade() -> None:
    for col in _FIELDS:
        # Existing rows may be NULL (stays NULL) or plain text — wrap non-null text as a JSON array.
        # NULL rows are kept NULL; empty-string rows become an empty JSON array.
        op.execute(
            f"""
            ALTER TABLE projects
            ALTER COLUMN {col}
            TYPE JSON
            USING CASE
                WHEN {col} IS NULL THEN NULL
                WHEN TRIM({col}) = '' THEN '[]'::json
                ELSE json_build_array({col})
            END
            """
        )


def downgrade() -> None:
    for col in _FIELDS:
        op.execute(
            f"""
            ALTER TABLE projects
            ALTER COLUMN {col}
            TYPE TEXT
            USING CASE
                WHEN {col} IS NULL THEN NULL
                ELSE {col}::text
            END
            """
        )
