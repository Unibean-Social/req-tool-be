"""add references nfr_note sync tables

Revision ID: a318c2b350cc
Revises: 8f89596258b8
Create Date: 2026-05-14 11:49:10.992949

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a318c2b350cc'
down_revision: Union[str, None] = '8f89596258b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create new enum types; item_type already exists from prior migration
    op.execute(sa.text("""
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sync_operation') THEN
        CREATE TYPE sync_operation AS ENUM ('create', 'update', 'close');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sync_queue_status') THEN
        CREATE TYPE sync_queue_status AS ENUM ('pending', 'failed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sync_log_status') THEN
        CREATE TYPE sync_log_status AS ENUM ('success', 'failed');
    END IF;
END $$;
"""))

    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS github_items (
    id UUID NOT NULL,
    item_type item_type NOT NULL,
    item_id UUID NOT NULL,
    github_issue_number INTEGER NOT NULL,
    github_issue_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT uq_github_item UNIQUE (item_type, item_id)
)
"""))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_github_items_item_id ON github_items (item_id)"))

    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS sync_queue (
    id UUID NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    item_type item_type NOT NULL,
    item_id UUID NOT NULL,
    operation sync_operation NOT NULL,
    body_snapshot JSONB NOT NULL,
    status sync_queue_status NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT uq_sync_queue_item UNIQUE (project_id, item_type, item_id)
)
"""))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_sync_queue_project_id ON sync_queue (project_id)"))

    op.execute(sa.text("""
CREATE TABLE IF NOT EXISTS sync_logs (
    id UUID NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sync_queue_id UUID REFERENCES sync_queue(id) ON DELETE SET NULL,
    item_type item_type NOT NULL,
    item_id UUID NOT NULL,
    operation sync_operation NOT NULL,
    status sync_log_status NOT NULL,
    error_code VARCHAR(50),
    error_message TEXT,
    github_issue_number INTEGER,
    github_issue_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
)
"""))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_sync_logs_item_id ON sync_logs (item_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_sync_logs_project_id ON sync_logs (project_id)"))

    op.add_column('epics', sa.Column('references', sa.JSON(), nullable=True))
    op.add_column('features', sa.Column('nfr_note', sa.Text(), nullable=True))
    op.add_column('features', sa.Column('references', sa.JSON(), nullable=True))
    op.add_column('stories', sa.Column('references', sa.JSON(), nullable=True))
    op.add_column('tasks', sa.Column('references', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'references')
    op.drop_column('stories', 'references')
    op.drop_column('features', 'references')
    op.drop_column('features', 'nfr_note')
    op.drop_column('epics', 'references')
    op.execute(sa.text("DROP INDEX IF EXISTS ix_sync_logs_project_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_sync_logs_item_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS sync_logs"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_sync_queue_project_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS sync_queue"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_github_items_item_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS github_items"))
    op.execute(sa.text("""
DO $$ BEGIN
    DROP TYPE IF EXISTS sync_log_status;
    DROP TYPE IF EXISTS sync_queue_status;
    DROP TYPE IF EXISTS sync_operation;
END $$;
"""))
