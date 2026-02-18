"""Show model and DB operations (caller passes session)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, Tuple

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import ts_created, ts_updated, uuid_pk


class Show(Base):
    """Show/competition. Only table with api_show_id (unique per show)."""

    __tablename__ = "shows"
    __table_args__ = (
        {"comment": "Shows/competitions. ONLY table with api_show_id (unique per show)."},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    farm_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    api_show_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[Optional[datetime]] = ts_updated()

    farm = relationship("Farm", backref="shows")


# -----------------------------------------------------------------------------
# DB operations (session passed by caller)
# -----------------------------------------------------------------------------


async def upsert_show(
    session: AsyncSession,
    farm_id: uuid.UUID,
    api_show_id: int,
    name: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Tuple[uuid.UUID, int, int]:
    """
    Inserts a new show in the `shows` table based on (farm_id, api_show_id).
    If a show with the same (farm_id, api_show_id) exists, returns its UUID and (0, 1),
    otherwise inserts a new show record and returns its UUID and (1, 0).

    Args:
        session: SQLAlchemy AsyncSession for DB access.
        farm_id: UUID of the farm to which the show belongs.
        api_show_id: External (Wellington API) show ID (unique per show).
        name: Name of the show.
        start_date: Start date of the show (optional).
        end_date: End date of the show (optional).

    Returns:
        (show_uuid, inserted_count, updated_count). One of inserted_count or updated_count is 1.
    """
    stmt_select = select(Show.id).where(
        Show.farm_id == farm_id,
        Show.api_show_id == api_show_id,
    )
    result = await session.execute(stmt_select)
    row = result.first()

    if row:
        return row[0], 0, 1
    stmt_insert = insert(Show.__table__).values(
        farm_id=farm_id,
        api_show_id=api_show_id,
        name=name,
        start_date=start_date,
        end_date=end_date,
    ).returning(Show.__table__.c.id)
    result = await session.execute(stmt_insert)
    new_row = result.one()
    return new_row[0], 1, 0
