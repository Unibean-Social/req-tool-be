"""add stakeholders, nfrs, project_business tables; story business_value; drop jsonb columns

Revision ID: e1f2a3b4c5d6
Revises: cd9f88c4ef70
Create Date: 2026-05-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "cd9f88c4ef70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # a) business_value on stories — idempotent
    col_exists = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='stories' AND column_name='business_value'"
    )).fetchone()
    if not col_exists:
        op.add_column("stories", sa.Column("business_value", sa.Integer(), nullable=True))

    # b) enums — drop orphaned types from partial runs, then recreate cleanly
    conn.execute(sa.text("DROP TYPE IF EXISTS influencelevel"))
    conn.execute(sa.text("DROP TYPE IF EXISTS nfrcategory"))
    conn.execute(sa.text("CREATE TYPE influencelevel AS ENUM ('high', 'medium', 'low')"))
    conn.execute(sa.text(
        "CREATE TYPE nfrcategory AS ENUM "
        "('performance', 'security', 'usability', 'reliability', 'compliance', 'maintainability')"
    ))

    # c) stakeholders table
    op.create_table(
        "stakeholders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("impact_area", sa.Text(), nullable=True),
        sa.Column("influence_level", postgresql.ENUM(name="influencelevel", create_type=False), nullable=False, server_default="medium"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # d) project_goals table
    op.create_table(
        "project_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # e) project_flows table
    op.create_table(
        "project_flows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # f) project_rules table
    op.create_table(
        "project_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("linked_feature_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("features.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # g) nfrs table
    op.create_table(
        "nfrs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("category", postgresql.ENUM(name="nfrcategory", create_type=False), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", postgresql.ENUM(name="priority", create_type=False), nullable=False, server_default="medium"),
        sa.Column("source_feature_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("features.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # h) Data migration: JSONB → relational rows

    # stakeholders
    projects = conn.execute(sa.text("SELECT id, stakeholders FROM projects WHERE stakeholders IS NOT NULL")).fetchall()
    for project_id, stakeholders_json in projects:
        if not stakeholders_json:
            continue
        items = stakeholders_json if isinstance(stakeholders_json, list) else []
        for item in items:
            try:
                conn.execute(sa.text("""
                    INSERT INTO stakeholders (id, project_id, name, role, impact_area, influence_level, notes)
                    VALUES (gen_random_uuid(), :pid, :name, :role, :impact, :influence, :notes)
                """), {
                    "pid": str(project_id),
                    "name": item.get("name", "Unknown") if isinstance(item, dict) else str(item),
                    "role": item.get("role") if isinstance(item, dict) else None,
                    "impact": item.get("impact_area") or item.get("concern") if isinstance(item, dict) else None,
                    "influence": item.get("influence_level", "medium") if isinstance(item, dict) else "medium",
                    "notes": item.get("notes") if isinstance(item, dict) else None,
                })
            except Exception as e:
                print(f"[migration] skipped stakeholder in project {project_id}: {e}")

    # business_goals → project_goals
    projects = conn.execute(sa.text("SELECT id, business_goals FROM projects WHERE business_goals IS NOT NULL")).fetchall()
    for project_id, goals_json in projects:
        items = goals_json if isinstance(goals_json, list) else []
        for i, item in enumerate(items):
            text = item if isinstance(item, str) else item.get("description", str(item)) if isinstance(item, dict) else str(item)
            try:
                conn.execute(sa.text(
                    'INSERT INTO project_goals (id, project_id, description, "order") VALUES (gen_random_uuid(), :pid, :desc, :ord)'
                ), {"pid": str(project_id), "desc": text, "ord": i})
            except Exception as e:
                print(f"[migration] skipped goal in project {project_id}: {e}")

    # business_flows → project_flows
    projects = conn.execute(sa.text("SELECT id, business_flows FROM projects WHERE business_flows IS NOT NULL")).fetchall()
    for project_id, flows_json in projects:
        items = flows_json if isinstance(flows_json, list) else []
        for i, item in enumerate(items):
            if isinstance(item, str):
                title, description = item, None
            elif isinstance(item, dict):
                title = item.get("title", item.get("name", "Flow"))
                description = item.get("description")
            else:
                title, description = str(item), None
            try:
                conn.execute(sa.text(
                    'INSERT INTO project_flows (id, project_id, title, description, "order") VALUES (gen_random_uuid(), :pid, :title, :desc, :ord)'
                ), {"pid": str(project_id), "title": title, "desc": description, "ord": i})
            except Exception as e:
                print(f"[migration] skipped flow in project {project_id}: {e}")

    # business_rules → project_rules
    projects = conn.execute(sa.text("SELECT id, business_rules FROM projects WHERE business_rules IS NOT NULL")).fetchall()
    for project_id, rules_json in projects:
        items = rules_json if isinstance(rules_json, list) else []
        for item in items:
            text = item if isinstance(item, str) else item.get("description", str(item)) if isinstance(item, dict) else str(item)
            try:
                conn.execute(sa.text(
                    "INSERT INTO project_rules (id, project_id, description) VALUES (gen_random_uuid(), :pid, :desc)"
                ), {"pid": str(project_id), "desc": text})
            except Exception as e:
                print(f"[migration] skipped rule in project {project_id}: {e}")

    # i) Drop legacy JSONB columns (last step — data already migrated)
    op.drop_column("projects", "stakeholders")
    op.drop_column("projects", "business_goals")
    op.drop_column("projects", "business_flows")
    op.drop_column("projects", "business_rules")

    # j) Drop nfr_note from features (replaced by nfrs table)
    op.drop_column("features", "nfr_note")


def downgrade() -> None:
    op.add_column("features", sa.Column("nfr_note", sa.Text(), nullable=True))

    op.add_column("projects", sa.Column("stakeholders", postgresql.JSONB(), nullable=True))
    op.add_column("projects", sa.Column("business_goals", postgresql.JSONB(), nullable=True))
    op.add_column("projects", sa.Column("business_flows", postgresql.JSONB(), nullable=True))
    op.add_column("projects", sa.Column("business_rules", postgresql.JSONB(), nullable=True))

    op.drop_table("nfrs")
    op.drop_table("stakeholders")
    op.drop_table("project_goals")
    op.drop_table("project_flows")
    op.drop_table("project_rules")
    op.drop_column("stories", "business_value")

    sa.Enum(name="nfrcategory").drop(op.get_bind())
    sa.Enum(name="influencelevel").drop(op.get_bind())

    sa.Enum(name="nfrcategory").drop(op.get_bind())
    sa.Enum(name="influencelevel").drop(op.get_bind())
