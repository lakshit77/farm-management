"""Add push_subscriptions table for Web Push notification device tokens.

Each row represents one browser/device subscription for one user.
A single user (user_id) may have many rows across multiple devices.

Revision ID: 20250321000000
Revises: 20250220100000
Create Date: 2025-03-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20250321000000"
down_revision: Union[str, None] = "20250220100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create push_subscriptions table."""
    op.create_table(
        "push_subscriptions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Supabase auth UID (text, not FK — auth schema is separate)
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "farm_id",
            UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The unique push endpoint URL assigned by the browser push service
        # (Google FCM, Apple APNs, Mozilla, etc.)
        sa.Column("endpoint", sa.Text(), nullable=False),
        # Encryption keys returned by pushManager.subscribe()
        sa.Column("p256dh_key", sa.Text(), nullable=False),
        sa.Column("auth_key", sa.Text(), nullable=False),
        # Optional human-readable device hint (e.g. "iPhone / Safari 17")
        sa.Column("user_agent", sa.Text(), nullable=True),
        # False when the subscription has expired (410 Gone from push service)
        # or the user disabled notifications on this device.
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Unique constraint: one endpoint URL is one device — no duplicates
    op.create_unique_constraint(
        "uq_push_subscriptions_endpoint",
        "push_subscriptions",
        ["endpoint"],
    )

    # Fast lookup: all active subscriptions for a given user
    op.create_index(
        "idx_push_subscriptions_user_active",
        "push_subscriptions",
        ["user_id", "is_active"],
    )

    # Fast lookup: all active subscriptions for an entire farm
    op.create_index(
        "idx_push_subscriptions_farm_active",
        "push_subscriptions",
        ["farm_id", "is_active"],
    )


def downgrade() -> None:
    """Drop push_subscriptions table."""
    op.drop_index("idx_push_subscriptions_farm_active", table_name="push_subscriptions")
    op.drop_index("idx_push_subscriptions_user_active", table_name="push_subscriptions")
    op.drop_constraint(
        "uq_push_subscriptions_endpoint",
        "push_subscriptions",
        type_="unique",
    )
    op.drop_table("push_subscriptions")
