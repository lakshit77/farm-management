"""Add is_own_entry, rider_list_text, trainer_name, owner_name to entries.

Supports the All Show Entries feature: distinguishes own entries (from
/entries/my) vs all-show entries (from /entries), and stores display-only
metadata from the all-entries API.

Revision ID: 20260412000000
Revises: 20250321000001
Create Date: 2026-04-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260412000000"
down_revision: Union[str, None] = "20250321000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRUE = sa.text("true")


def upgrade() -> None:
    """Add columns and index for all-show entries support."""
    op.add_column(
        "entries",
        sa.Column("is_own_entry", sa.Boolean(), nullable=False, server_default=_TRUE),
    )
    op.add_column(
        "entries",
        sa.Column("rider_list_text", sa.String(500), nullable=True),
    )
    op.add_column(
        "entries",
        sa.Column("trainer_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "entries",
        sa.Column("owner_name", sa.String(255), nullable=True),
    )
    op.create_index(
        "idx_entries_show_is_own",
        "entries",
        ["show_id", "is_own_entry"],
    )


def downgrade() -> None:
    """Remove all-show entries columns and index."""
    op.drop_index("idx_entries_show_is_own", table_name="entries")
    op.drop_column("entries", "owner_name")
    op.drop_column("entries", "trainer_name")
    op.drop_column("entries", "rider_list_text")
    op.drop_column("entries", "is_own_entry")
