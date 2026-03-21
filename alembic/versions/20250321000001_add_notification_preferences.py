"""Add user_notification_preferences table for per-category push notification toggles.

One row per user (shared across all their devices). Each boolean column
controls whether that category of push notification is sent to the user.
All categories default to True (opt-out model within push permission).

Revision ID: 20250321000001
Revises: 20250321000000
Create Date: 2025-03-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20250321000001"
down_revision: Union[str, None] = "20250321000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRUE = sa.text("true")


def upgrade() -> None:
    """Create user_notification_preferences table."""
    op.create_table(
        "user_notification_preferences",
        # Supabase auth UID — one row per user
        sa.Column("user_id", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "farm_id",
            UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ── Chat preferences ────────────────────────────────────────────────
        sa.Column("chat_all_team", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column("chat_admin", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column("chat_dm", sa.Boolean(), nullable=False, server_default=_TRUE),
        # ── Show event preferences ──────────────────────────────────────────
        sa.Column("class_status", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column("time_changes", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column("results", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column("horse_completed", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column("scratched", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column("progress_updates", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column("morning_summary", sa.Boolean(), nullable=False, server_default=_TRUE),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Index for fast farm-wide preference lookups
    op.create_index(
        "idx_notif_prefs_farm_id",
        "user_notification_preferences",
        ["farm_id"],
    )


def downgrade() -> None:
    """Drop user_notification_preferences table."""
    op.drop_index("idx_notif_prefs_farm_id", table_name="user_notification_preferences")
    op.drop_table("user_notification_preferences")
