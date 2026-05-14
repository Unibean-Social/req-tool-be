"""add unique constraints on prefix columns

Revision ID: c7e2f4a8b931
Revises: a318c2b350cc
Create Date: 2026-05-14 14:00:00.000000

"""
from alembic import op

revision = "c7e2f4a8b931"
down_revision = "a318c2b350cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_epics_project_prefix", "epics", ["project_id", "prefix"])
    op.create_unique_constraint("uq_features_epic_prefix", "features", ["epic_id", "prefix"])
    op.create_unique_constraint("uq_stories_feature_prefix", "stories", ["feature_id", "prefix"])
    op.create_unique_constraint("uq_tasks_story_prefix", "tasks", ["story_id", "prefix"])


def downgrade() -> None:
    op.drop_constraint("uq_tasks_story_prefix", "tasks", type_="unique")
    op.drop_constraint("uq_stories_feature_prefix", "stories", type_="unique")
    op.drop_constraint("uq_features_epic_prefix", "features", type_="unique")
    op.drop_constraint("uq_epics_project_prefix", "epics", type_="unique")
