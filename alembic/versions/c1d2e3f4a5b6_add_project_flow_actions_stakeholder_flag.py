"""add project_flow_actions, reshape project_flows, stakeholder is_business_actor

Revision ID: c1d2e3f4a5b6
Revises: b3c4d5e6f7a8
Create Date: 2026-05-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Reshape project_flows ──────────────────────────────────────────────
    op.alter_column("project_flows", "title", new_column_name="name")
    op.drop_column("project_flows", "order")
    op.add_column("project_flows", sa.Column("code", sa.Text(), nullable=False, server_default=""))
    op.alter_column("project_flows", "code", server_default=None)
    op.create_unique_constraint(
        "uq_project_flows_project_code", "project_flows", ["project_id", "code"]
    )

    # ── 2. Create project_flow_actions ────────────────────────────────────────
    op.create_table(
        "project_flow_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("project_flows.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stakeholders.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )

    # ── 3. Create project_flow_action_rules junction ──────────────────────────
    op.create_table(
        "project_flow_action_rules",
        sa.Column("action_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("project_flow_actions.id", ondelete="CASCADE"),
                  nullable=False, primary_key=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("project_rules.id", ondelete="CASCADE"),
                  nullable=False, primary_key=True),
    )
    op.create_index("ix_flow_action_rules_action", "project_flow_action_rules", ["action_id"])
    op.create_index("ix_flow_action_rules_rule",   "project_flow_action_rules", ["rule_id"])

    # ── 4. Stakeholder: add is_business_actor ─────────────────────────────────
    op.add_column("stakeholders", sa.Column(
        "is_business_actor", sa.Boolean(), nullable=False, server_default=sa.false()
    ))
    op.alter_column("stakeholders", "is_business_actor", server_default=None)


def downgrade() -> None:
    op.drop_column("stakeholders", "is_business_actor")

    op.drop_index("ix_flow_action_rules_rule",   table_name="project_flow_action_rules")
    op.drop_index("ix_flow_action_rules_action", table_name="project_flow_action_rules")
    op.drop_table("project_flow_action_rules")
    op.drop_table("project_flow_actions")

    op.drop_constraint("uq_project_flows_project_code", "project_flows", type_="unique")
    op.drop_column("project_flows", "code")
    op.add_column("project_flows", sa.Column(
        "order", sa.Integer(), nullable=False, server_default="0"
    ))
    op.alter_column("project_flows", "order", server_default=None)
    op.alter_column("project_flows", "name", new_column_name="title")
