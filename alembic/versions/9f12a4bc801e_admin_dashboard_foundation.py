"""admin dashboard foundation

Revision ID: 9f12a4bc801e
Revises: 28e38c9fe6ad
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f12a4bc801e"
down_revision: str | None = "28e38c9fe6ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("admin_role", sa.String(24), nullable=True))
        batch.add_column(
            sa.Column("account_status", sa.String(16), nullable=False, server_default="active")
        )
        batch.add_column(sa.Column("last_active_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_users_admin_role", ["admin_role"])
        batch.create_index("ix_users_account_status", ["account_status"])

    with op.batch_alter_table("sources") as batch:
        batch.add_column(sa.Column("region", sa.String(64), nullable=True))
        batch.add_column(sa.Column("category", sa.String(32), nullable=True))
        batch.add_column(
            sa.Column("source_type", sa.String(24), nullable=False, server_default="rss")
        )
        batch.add_column(sa.Column("last_successful_fetch", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("reliability_notes", sa.Text(), nullable=True))
        batch.create_index("ix_sources_region", ["region"])
        batch.create_index("ix_sources_category", ["category"])

    with op.batch_alter_table("articles") as batch:
        batch.add_column(
            sa.Column("status", sa.String(16), nullable=False, server_default="collected")
        )
        batch.add_column(sa.Column("failure_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ingestion_run_id", sa.String(32), nullable=True))
        batch.create_index("ix_articles_status", ["status"])
        batch.create_index("ix_articles_ingestion_run_id", ["ingestion_run_id"])
        batch.create_foreign_key(
            "fk_articles_ingestion_run_id", "ingestion_runs", ["ingestion_run_id"], ["id"]
        )

    with op.batch_alter_table("stories") as batch:
        batch.add_column(
            sa.Column("status", sa.String(24), nullable=False, server_default="published")
        )
        batch.add_column(sa.Column("editor_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("published_by_id", sa.String(32), nullable=True))
        batch.create_index("ix_stories_status", ["status"])
        batch.create_index("ix_stories_published_at", ["published_at"])
        batch.create_foreign_key(
            "fk_stories_published_by_id", "users", ["published_by_id"], ["id"]
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


def downgrade() -> None:
    op.drop_table("admin_settings")
    op.drop_table("audit_logs")
    with op.batch_alter_table("stories") as batch:
        batch.drop_constraint("fk_stories_published_by_id", type_="foreignkey")
        batch.drop_index("ix_stories_published_at")
        batch.drop_index("ix_stories_status")
        batch.drop_column("published_by_id")
        batch.drop_column("published_at")
        batch.drop_column("editor_notes")
        batch.drop_column("status")
    with op.batch_alter_table("articles") as batch:
        batch.drop_constraint("fk_articles_ingestion_run_id", type_="foreignkey")
        batch.drop_index("ix_articles_ingestion_run_id")
        batch.drop_index("ix_articles_status")
        batch.drop_column("ingestion_run_id")
        batch.drop_column("failure_reason")
        batch.drop_column("status")
    with op.batch_alter_table("sources") as batch:
        batch.drop_index("ix_sources_category")
        batch.drop_index("ix_sources_region")
        for column in (
            "reliability_notes",
            "last_error",
            "failure_count",
            "last_successful_fetch",
            "source_type",
            "category",
            "region",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_account_status")
        batch.drop_index("ix_users_admin_role")
        batch.drop_column("last_active_at")
        batch.drop_column("account_status")
        batch.drop_column("admin_role")
