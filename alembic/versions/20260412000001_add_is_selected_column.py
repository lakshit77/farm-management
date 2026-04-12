"""Add is_selected column to entries table.

Controls visibility of entries across all tabs (overview, classes, rings,
notifications). Own entries default to true (visible), external entries
from the all-entries sync default to false (hidden until toggled on).

Revision ID: 20260412000001
Revises: 20260412000000
Create Date: 2026-04-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260412000001"
down_revision: Union[str, None] = "20260412000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRUE = sa.text("true")


def upgrade() -> None:
    """Add is_selected boolean column with server_default=true."""
    op.add_column(
        "entries",
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=_TRUE),
    )


def downgrade() -> None:
    """Remove is_selected column."""
    op.drop_column("entries", "is_selected")
