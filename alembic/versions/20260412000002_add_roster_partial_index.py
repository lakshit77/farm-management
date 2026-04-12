"""Add partial index for Show Entries roster query.

Speeds up the GET /entries/all endpoint which queries roster rows
(api_class_id IS NULL) ordered by back_number for a given show.

Revision ID: 20260412000002
Revises: 20260412000001
Create Date: 2026-04-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260412000002"
down_revision: Union[str, None] = "20260412000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add partial index on (show_id, back_number) WHERE api_class_id IS NULL."""
    op.create_index(
        "idx_entries_show_roster",
        "entries",
        ["show_id", "back_number"],
        postgresql_where=sa.text("api_class_id IS NULL"),
    )


def downgrade() -> None:
    """Remove roster partial index."""
    op.drop_index("idx_entries_show_roster", table_name="entries")
