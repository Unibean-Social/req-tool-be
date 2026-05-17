"""nfr multi-feature links: replace source_feature_id with junction table

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-05-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # a) Create junction table
    op.create_table(
        "nfr_feature_links",
        sa.Column("nfr_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nfrs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("features.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("nfr_id", "feature_id"),
    )
    op.create_index("ix_nfr_feature_links_feature_id", "nfr_feature_links", ["feature_id"])

    # b) Migrate existing source_feature_id → junction rows
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO nfr_feature_links (nfr_id, feature_id)
        SELECT id, source_feature_id
        FROM nfrs
        WHERE source_feature_id IS NOT NULL
    """))

    # c) Drop legacy column
    op.drop_column("nfrs", "source_feature_id")


def downgrade() -> None:
    # Re-add column
    op.add_column("nfrs", sa.Column(
        "source_feature_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("features.id", ondelete="SET NULL"),
        nullable=True,
    ))

    # Copy first link back per NFR — deterministic order; multi-feature data is lost (by design)
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE nfrs n
        SET source_feature_id = (
            SELECT feature_id FROM nfr_feature_links
            WHERE nfr_id = n.id
            ORDER BY feature_id
            LIMIT 1
        )
    """))

    op.drop_index("ix_nfr_feature_links_feature_id", table_name="nfr_feature_links")
    op.drop_table("nfr_feature_links")
