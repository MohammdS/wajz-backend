"""remove the retired admin stack

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("admin_settings")
    op.drop_table("audit_logs")

    with op.batch_alter_table("ongoing_topics") as batch:
        batch.drop_column("published_by_id")

    with op.batch_alter_table("stories") as batch:
        batch.drop_constraint("fk_stories_published_by_id", type_="foreignkey")
        batch.drop_column("published_by_id")
        batch.drop_column("editor_notes")

    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_admin_role")
        batch.drop_column("admin_role")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("admin_role", sa.String(24), nullable=True))
        batch.create_index("ix_users_admin_role", ["admin_role"])

    with op.batch_alter_table("stories") as batch:
        batch.add_column(sa.Column("editor_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("published_by_id", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_stories_published_by_id",
            "users",
            ["published_by_id"],
            ["id"],
        )

    with op.batch_alter_table("ongoing_topics") as batch:
        batch.add_column(sa.Column("published_by_id", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_ongoing_topics_published_by_id",
            "users",
            ["published_by_id"],
            ["id"],
        )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("actor_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=False),
        sa.Column("actor_role", sa.String(24), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("actor_user_id", "action", "target_type", "target_id", "created_at"):
        op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])

    op.create_table(
        "admin_settings",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
