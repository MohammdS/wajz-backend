"""add onboarding completed

Revision ID: 28e38c9fe6ad
Revises: 617644151552
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "28e38c9fe6ad"
down_revision: str | None = "617644151552"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Existing preference rows belong to users who already passed the old
    # device-local onboarding flow. Only future accounts should start false.
    op.execute(
        sa.text(
            "UPDATE user_preferences "
            "SET onboarding_completed = true"
        )
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "onboarding_completed")
