"""Rider model and DB operations (caller passes session)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import ForeignKey, select, String
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import ts_created, ts_updated, uuid_pk


class Rider(Base):
    """Rider belonging to a farm. Matched by NAME when syncing."""

    __tablename__ = "riders"
    __table_args__ = (
        {"comment": "Riders belonging to a farm. Matched by NAME when syncing."},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    farm_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[Optional[datetime]] = ts_updated()

    farm = relationship("Farm", backref="riders")


# -----------------------------------------------------------------------------
# DB operations (session passed by caller)
# -----------------------------------------------------------------------------


async def bulk_upsert_riders(
    session: AsyncSession,
    farm_id: uuid.UUID,
    names: List[str],
) -> None:
    """Bulk insert riders ON CONFLICT (farm_id, name) DO NOTHING."""
    if not names:
        return
    names = list(dict.fromkeys(names))
    stmt = insert(Rider.__table__).values(
        [{"farm_id": farm_id, "name": name} for name in names]
    ).on_conflict_do_nothing(index_elements=["farm_id", "name"])
    await session.execute(stmt)


async def get_rider_ids_by_names(
    session: AsyncSession,
    farm_id: uuid.UUID,
    names: List[str],
) -> List[Tuple[uuid.UUID, str]]:
    """Return (id, name) for riders with given names in this farm."""
    if not names:
        return []
    result = await session.execute(
        select(Rider.id, Rider.name).where(
            Rider.farm_id == farm_id,
            Rider.name.in_(names),
        )
    )
    return list(result.all())
