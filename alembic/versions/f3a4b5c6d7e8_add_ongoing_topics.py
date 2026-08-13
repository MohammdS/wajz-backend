"""add ongoing news topics

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ongoing_topics",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("category", sa.String(32), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("published_by_id", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("category", "priority", "status", "expires_at", "published_at"):
        op.create_index(f"ix_ongoing_topics_{column}", "ongoing_topics", [column])

    op.create_table(
        "ongoing_topic_translations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "topic_id",
            sa.String(32),
            sa.ForeignKey("ongoing_topics.id"),
            nullable=False,
        ),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "topic_id",
            "language",
            name="uq_ongoing_topic_translation_language",
        ),
    )
    op.create_index(
        "ix_ongoing_topic_translations_topic_id",
        "ongoing_topic_translations",
        ["topic_id"],
    )
    op.create_index(
        "ix_ongoing_topic_translations_language",
        "ongoing_topic_translations",
        ["language"],
    )

    op.create_table(
        "ongoing_topic_stories",
        sa.Column(
            "topic_id",
            sa.String(32),
            sa.ForeignKey("ongoing_topics.id"),
            primary_key=True,
        ),
        sa.Column(
            "story_id",
            sa.String(32),
            sa.ForeignKey("stories.id"),
            primary_key=True,
        ),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_ongoing_topic_stories_story_id",
        "ongoing_topic_stories",
        ["story_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ongoing_topic_stories_story_id", table_name="ongoing_topic_stories"
    )
    op.drop_table("ongoing_topic_stories")
    op.drop_index(
        "ix_ongoing_topic_translations_language",
        table_name="ongoing_topic_translations",
    )
    op.drop_index(
        "ix_ongoing_topic_translations_topic_id",
        table_name="ongoing_topic_translations",
    )
    op.drop_table("ongoing_topic_translations")
    for column in ("published_at", "expires_at", "status", "priority", "category"):
        op.drop_index(f"ix_ongoing_topics_{column}", table_name="ongoing_topics")
    op.drop_table("ongoing_topics")
