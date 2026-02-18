"""Horse model and DB operations (caller passes session)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import ForeignKey, select, String
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import EntryStatus
from app.models.base import ts_created, ts_updated, uuid_pk


class Horse(Base):
    """Horse belonging to a farm. Matched by NAME when syncing."""

    __tablename__ = "horses"
    __table_args__ = (
        {"comment": "Horses belonging to a farm. Matched by NAME when syncing."},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    farm_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=EntryStatus.ACTIVE.value, nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[Optional[datetime]] = ts_updated()

    farm = relationship("Farm", backref="horses")


# -----------------------------------------------------------------------------
# DB operations (session passed by caller)
# -----------------------------------------------------------------------------


async def bulk_upsert_horses(
    session: AsyncSession,
    farm_id: uuid.UUID,
    names: List[str],
) -> Tuple[int, int]:
    """
    Bulk insert horses ON CONFLICT (farm_id, name) DO NOTHING.

    Returns:
        (inserted_count, updated_count). updated_count is always 0 (DO NOTHING).
    """
    if not names:
        return 0, 0
    names = list(dict.fromkeys(names))  # unique order-preserving
    stmt = insert(Horse.__table__).values(
        [{"farm_id": farm_id, "name": name} for name in names]
    ).on_conflict_do_nothing(index_elements=["farm_id", "name"]).returning(Horse.id)
    result = await session.execute(stmt)
    inserted = len(result.all())
    return inserted, 0


async def get_horse_ids_by_names(
    session: AsyncSession,
    farm_id: uuid.UUID,
    names: List[str],
) -> List[Tuple[uuid.UUID, str]]:
    """Return (id, name) for horses with given names in this farm."""
    if not names:
        return []
    result = await session.execute(
        select(Horse.id, Horse.name).where(
            Horse.farm_id == farm_id,
            Horse.name.in_(names),
        )
    )
    return list(result.all())