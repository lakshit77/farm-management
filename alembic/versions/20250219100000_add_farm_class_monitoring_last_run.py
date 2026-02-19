"""Add class_monitoring_last_run_at to farms for per-farm last run (Flow 2).

Revision ID: 20250219100000
Revises: 20250218150000
Create Date: 2025-02-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250219100000"
down_revision: Union[str, None] = "20250218150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "farms",
        sa.Column(
            "class_monitoring_last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When class monitoring (Flow 2) last ran for this farm (UTC).",
        ),
    )


def downgrade() -> None:
    op.drop_column("farms", "class_monitoring_last_run_at")
