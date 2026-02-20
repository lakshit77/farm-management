"""Add indexes for Postgres best practices: horse_location_history FKs.

- horse_location_history: index FK columns for JOINs and CASCADE (location_id, show_id,
  event_id, class_id, entry_id). horse_id already indexed.

Note: farms table is not indexed (expected ≤5 rows; full scan is negligible).

Revision ID: 20250220100000
Revises: 20250219100000
Create Date: 2025-02-20

"""
from typing import Sequence, Union

from alembic import op


revision: str = "20250220100000"
down_revision: Union[str, None] = "20250219100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # horse_location_history: index FK columns for JOINs and CASCADE
    op.create_index(
        "idx_horse_location_history_location_id",
        "horse_location_history",
        ["location_id"],
        unique=False,
    )
    op.create_index(
        "idx_horse_location_history_show_id",
        "horse_location_history",
        ["show_id"],
        unique=False,
    )
    op.create_index(
        "idx_horse_location_history_event_id",
        "horse_location_history",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        "idx_horse_location_history_class_id",
        "horse_location_history",
        ["class_id"],
        unique=False,
    )
    op.create_index(
        "idx_horse_location_history_entry_id",
        "horse_location_history",
        ["entry_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_horse_location_history_entry_id", table_name="horse_location_history")
    op.drop_index("idx_horse_location_history_class_id", table_name="horse_location_history")
    op.drop_index("idx_horse_location_history_event_id", table_name="horse_location_history")
    op.drop_index("idx_horse_location_history_show_id", table_name="horse_location_history")
    op.drop_index("idx_horse_location_history_location_id", table_name="horse_location_history")
