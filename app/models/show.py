"""Show model and DB operations (caller passes session)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

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
) -> uuid.UUID:
    """
    Insert or update show on (farm_id, api_show_id). Returns show id.
    """
    stmt = insert(Show.__table__).values(
        farm_id=farm_id,
        api_show_id=api_show_id,
        name=name,
        start_date=start_date,
        end_date=end_date,
    ).on_conflict_do_update(
        index_elements=["farm_id", "api_show_id"],
        index_where=text("api_show_id IS NOT NULL"),  # matches partial unique index idx_shows_farm_api
        set_={
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "updated_at": datetime.now(timezone.utc),
        },
    ).returning(Show.__table__.c.id)
    result = await session.execute(stmt)
    row = result.one()
    return row[0]
