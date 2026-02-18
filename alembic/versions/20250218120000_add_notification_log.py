"""Add notification_log table for class monitoring and future flow change events.

Revision ID: 20250218120000
Revises: 20250213000000
Create Date: 2025-02-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20250218120000"
down_revision: Union[str, None] = "20250213000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Log of all change notifications from class monitoring and future flows (horse availability, etc.).",
    )
    op.create_index(
        "idx_notification_log_farm_created",
        "notification_log",
        ["farm_id", "created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index("idx_notification_log_farm_id", "notification_log", ["farm_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_notification_log_farm_id", table_name="notification_log")
    op.drop_index("idx_notification_log_farm_created", table_name="notification_log")
    op.drop_table("notification_log")
