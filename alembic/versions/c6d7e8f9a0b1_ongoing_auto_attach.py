"""record automatic ongoing-topic matches

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: str | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ongoing_topic_stories") as batch:
        batch.add_column(
            sa.Column("added_by", sa.String(16), nullable=False, server_default="manual")
        )
        batch.add_column(sa.Column("match_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("match_reason", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("ongoing_topic_stories") as batch:
        batch.drop_column("match_reason")
        batch.drop_column("match_score")
        batch.drop_column("added_by")
