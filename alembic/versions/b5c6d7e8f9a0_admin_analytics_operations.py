"""add owner admin, analytics, privacy, and queued operations

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stories") as batch:
        batch.add_column(sa.Column("editor_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("published_by_id", sa.String(32), nullable=True))
        batch.create_foreign_key("fk_stories_published_by_id", "users", ["published_by_id"], ["id"])
    with op.batch_alter_table("ongoing_topics") as batch:
        batch.add_column(sa.Column("published_by_id", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_ongoing_topics_published_by_id",
            "users",
            ["published_by_id"],
            ["id"],
        )

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("actor_user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_email", sa.String(255), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "actor_user_id",
        "action",
        "target_type",
        "target_id",
        "request_id",
        "created_at",
    ):
        op.create_index(f"ix_admin_audit_logs_{column}", "admin_audit_logs", [column])

    op.create_table(
        "admin_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("job_type", sa.String(48), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("requested_by_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "job_type",
        "status",
        "requested_by_id",
        "idempotency_key",
        "next_attempt_at",
    ):
        op.create_index(
            f"ix_admin_jobs_{column}",
            "admin_jobs",
            [column],
            unique=column == "idempotency_key",
        )

    op.create_table(
        "operational_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_id", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "analytics_installations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_analytics_installations_created_at", "analytics_installations", ["created_at"]
    )
    op.create_index(
        "ix_analytics_installations_last_seen_at",
        "analytics_installations",
        ["last_seen_at"],
    )

    op.create_table(
        "privacy_acknowledgements",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "installation_id",
            sa.String(32),
            sa.ForeignKey("analytics_installations.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False, server_default="ar"),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
    )
    for column in (
        "installation_id",
        "user_id",
        "policy_version",
        "accepted_at",
        "withdrawn_at",
    ):
        op.create_index(
            f"ix_privacy_acknowledgements_{column}",
            "privacy_acknowledgements",
            [column],
        )

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "installation_id",
            sa.String(32),
            sa.ForeignKey("analytics_installations.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(48), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("locale", sa.String(8), nullable=True),
        sa.Column("platform", sa.String(16), nullable=True),
        sa.Column("app_version", sa.String(24), nullable=True),
    )
    for column in (
        "installation_id",
        "user_id",
        "session_id",
        "name",
        "occurred_at",
        "received_at",
        "entity_type",
        "entity_id",
        "locale",
        "platform",
    ):
        op.create_index(f"ix_analytics_events_{column}", "analytics_events", [column])

    op.create_table(
        "analytics_daily_aggregates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("metric", sa.String(48), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_analytics_daily_aggregates_day", "analytics_daily_aggregates", ["day"])
    op.create_index(
        "ix_analytics_daily_aggregates_metric",
        "analytics_daily_aggregates",
        ["metric"],
    )


def downgrade() -> None:
    op.drop_table("analytics_daily_aggregates")
    op.drop_table("analytics_events")
    op.drop_table("privacy_acknowledgements")
    op.drop_table("analytics_installations")
    op.drop_table("operational_settings")
    op.drop_table("admin_jobs")
    op.drop_table("admin_audit_logs")
    with op.batch_alter_table("ongoing_topics") as batch:
        batch.drop_constraint("fk_ongoing_topics_published_by_id", type_="foreignkey")
        batch.drop_column("published_by_id")
    with op.batch_alter_table("stories") as batch:
        batch.drop_constraint("fk_stories_published_by_id", type_="foreignkey")
        batch.drop_column("published_by_id")
        batch.drop_column("editor_notes")
