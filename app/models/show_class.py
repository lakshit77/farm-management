"""Show class model and DB operations (caller passes session)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import ForeignKey, Numeric, select, String
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import ts_created, ts_updated, uuid_pk


class ShowClass(Base):
    """Class (e.g. '$150 Green Conformation Hunter Model'). Matched by NAME."""

    __tablename__ = "classes"
    __table_args__ = (
        {"comment": "Class names ($15,000 Junior Jumper). Matched by NAME."},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    farm_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    class_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sponsor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prize_money: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )
    class_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    jumper_table: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[Optional[datetime]] = ts_updated()

    farm = relationship("Farm", backref="show_classes")


# -----------------------------------------------------------------------------
# DB operations (session passed by caller)
# -----------------------------------------------------------------------------


async def bulk_upsert_classes(
    session: AsyncSession,
    farm_id: uuid.UUID,
    rows: List[Tuple[str, Optional[str], Optional[str], Optional[Decimal], Optional[str]]],
) -> None:
    """
    Bulk insert/update classes. Each row is (name, class_number, sponsor, prize_money, class_type).
    Uses ON CONFLICT (farm_id, name, class_number).
    """
    if not rows:
        return
    stmt = insert(ShowClass.__table__).values(
        [
            {
                "farm_id": farm_id,
                "name": name,
                "class_number": class_number,
                "sponsor": sponsor,
                "prize_money": prize_money,
                "class_type": class_type,
            }
            for name, class_number, sponsor, prize_money, class_type in rows
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["farm_id", "name", "class_number"],
        set_={
            "sponsor": stmt.excluded.sponsor,
            "prize_money": stmt.excluded.prize_money,
            "class_type": stmt.excluded.class_type,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await session.execute(stmt)


async def get_classes_by_farm_keys(
    session: AsyncSession,
    farm_id: uuid.UUID,
    keys: List[Tuple[str, Optional[str]]],
) -> List[Tuple[uuid.UUID, str, Optional[str]]]:
    """Return (id, name, class_number) for classes matching (name, class_number) in keys."""
    if not keys:
        return []
    from sqlalchemy import and_, or_
    conditions = or_(
        *[and_(ShowClass.name == n, ShowClass.class_number == cn) for n, cn in keys]
    )
    result = await session.execute(
        select(ShowClass.id, ShowClass.name, ShowClass.class_number).where(
            ShowClass.farm_id == farm_id,
            conditions,
        )
    )
    return list(result.all())
