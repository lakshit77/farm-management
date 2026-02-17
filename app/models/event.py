"""Event model and DB operations (caller passes session)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import ForeignKey, Integer, select, String, Text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import ts_created, ts_updated, uuid_pk


class Event(Base):
    """Ring/event. Name is e.g. 'International Ring', 'Denemethy'. Matched by NAME."""

    __tablename__ = "events"
    __table_args__ = (
        {"comment": "Ring names (International Ring, etc.). Matched by NAME."},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    farm_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ring_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[Optional[datetime]] = ts_updated()

    farm = relationship("Farm", backref="events")


# -----------------------------------------------------------------------------
# DB operations (session passed by caller)
# -----------------------------------------------------------------------------


async def bulk_upsert_events(
    session: AsyncSession,
    farm_id: uuid.UUID,
    rows: List[Tuple[str, Optional[int]]],
) -> None:
    """
    Bulk insert/update events. Each row is (name, ring_number).
    Uses ON CONFLICT (farm_id, name). Caller can then select by farm_id to get id map.
    """
    if not rows:
        return
    stmt = insert(Event.__table__).values(
        [
            {"farm_id": farm_id, "name": name, "ring_number": rn}
            for name, rn in rows
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["farm_id", "name"],
        set_={
            "ring_number": stmt.excluded.ring_number,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await session.execute(stmt)


async def get_events_by_farm_for_rings(
    session: AsyncSession,
    farm_id: uuid.UUID,
) -> List[Tuple[uuid.UUID, str, Optional[int]]]:
    """Return (id, name, ring_number) for all events of the farm. Used to build ring_number → id map."""
    result = await session.execute(
        select(Event.id, Event.name, Event.ring_number).where(Event.farm_id == farm_id)
    )
    return list(result.all())
