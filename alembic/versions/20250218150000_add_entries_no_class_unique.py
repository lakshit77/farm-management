"""Add partial unique index on entries for (horse_id, show_id) when api_class_id IS NULL.

Allows one "no class" entry per horse per show for horses in "my entries" but not in any class.
Revision ID: 20250218150000
Revises: 20250218120000
Create Date: 2025-02-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250218150000"
down_revision: Union[str, None] = "20250218120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_entries_unique_no_class",
        "entries",
        ["horse_id", "show_id"],
        unique=True,
        postgresql_where=sa.text("api_class_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_entries_unique_no_class", table_name="entries")
