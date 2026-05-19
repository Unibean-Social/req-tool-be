"""brd improvements: SMART goal fields, project scope/exec fields, project_constraints, project_goal_objectives, project_business_requirements

Revision ID: e2f3a4b5c6d7
Revises: d5e6f7a8b9c0
Create Date: 2026-05-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Enum types — drop orphaned types from partial runs, then recreate cleanly
    conn.execute(sa.text("DROP TYPE IF EXISTS goalpriority"))
    conn.execute(sa.text("DROP TYPE IF EXISTS constrainttype"))
    conn.execute(sa.text("DROP TYPE IF EXISTS constraintseverity"))
    conn.execute(sa.text("CREATE TYPE goalpriority AS ENUM ('high', 'medium', 'low')"))
    conn.execute(sa.text("CREATE TYPE constrainttype AS ENUM ('budget', 'timeline', 'technical', 'resource', 'regulatory')"))
    conn.execute(sa.text("CREATE TYPE constraintseverity AS ENUM ('high', 'medium', 'low')"))

    # Extend project_goals with SMART fields
    op.add_column("project_goals", sa.Column(
        "priority",
        postgresql.ENUM(name="goalpriority", create_type=False),
        nullable=False,
        server_default="medium",
    ))
    op.execute("ALTER TABLE project_goals ALTER COLUMN priority DROP DEFAULT")
    op.add_column("project_goals", sa.Column("success_metric", sa.Text(), nullable=True))
    op.add_column("project_goals", sa.Column("target_date", sa.Date(), nullable=True))

    # Extend projects with BRD scope + executive fields
    op.add_column("projects", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("budget", sa.Numeric(12, 2), nullable=True))
    op.add_column("projects", sa.Column("executive_summary", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("roi_notes", sa.Text(), nullable=True))

    # Create project_constraints table
    op.create_table(
        "project_constraints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", postgresql.ENUM(name="constrainttype", create_type=False), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", postgresql.ENUM(name="constraintseverity", create_type=False), nullable=False, server_default="medium"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("ALTER TABLE project_constraints ALTER COLUMN severity DROP DEFAULT")

    # Create project_goal_objectives table (text-only, no is_met)
    op.create_table(
        "project_goal_objectives",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_goals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # Create project_business_requirements table
    # priority stored as VARCHAR (reuses high/medium/low values, no new PG enum — avoids goalpriority naming collision)
    op.create_table(
        "project_business_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.VARCHAR(), nullable=False, server_default="medium"),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("project_business_requirements")
    op.drop_table("project_goal_objectives")
    op.drop_table("project_constraints")

    op.drop_column("project_goals", "target_date")
    op.drop_column("project_goals", "success_metric")
    op.drop_column("project_goals", "priority")

    op.drop_column("projects", "roi_notes")
    op.drop_column("projects", "executive_summary")
    op.drop_column("projects", "budget")
    op.drop_column("projects", "end_date")
    op.drop_column("projects", "start_date")

    conn = op.get_bind()
    conn.execute(sa.text("DROP TYPE IF EXISTS goalpriority"))
    conn.execute(sa.text("DROP TYPE IF EXISTS constrainttype"))
    conn.execute(sa.text("DROP TYPE IF EXISTS constraintseverity"))
