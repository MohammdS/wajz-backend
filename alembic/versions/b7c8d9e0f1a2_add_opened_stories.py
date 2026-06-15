"""add opened stories

Revision ID: b7c8d9e0f1a2
Revises: 9f12a4bc801e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "9f12a4bc801e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opened_stories",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("story_id", sa.String(length=32), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "story_id"),
    )


def downgrade() -> None:
    op.drop_table("opened_stories")
