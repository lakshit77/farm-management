"""Add ring_number column to entries for per-show accurate ring display.

Stores the display ring number (e.g. 7) per entry at sync time, so the
schedule view can show the correct ring for each historical show instead
of reading the shared (potentially stale) value from the events table.

Revision ID: 20260417000000
Revises: 20260412000002
Create Date: 2026-04-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260417000000"
down_revision: Union[str, None] = "20260412000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entries", sa.Column("ring_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("entries", "ring_number")
