"""add stable external auth subject

Revision ID: e2f3a4b5c6d7
Revises: c8d9e0f1a2b3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("auth_subject", sa.String(128), nullable=True))
        batch.create_index("ix_users_auth_subject", ["auth_subject"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_auth_subject")
        batch.drop_column("auth_subject")
