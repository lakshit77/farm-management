"""Entry model and DB operations (caller passes session)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    and_,
    select,
    text,
    tuple_,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import EntryStatus
from app.models.base import ts_created, ts_updated, uuid_pk


class Entry(Base):
    """Horse participation in a class. All api_* IDs stored here (show-specific)."""

    __tablename__ = "entries"
    __table_args__ = (
        {
            "comment": "Horse participation in class. ALL api_* IDs stored here (show-specific).",
        },
    )

    # Internal references (UUIDs)
    id: Mapped[uuid.UUID] = uuid_pk()
    horse_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"),
        nullable=False,
    )
    rider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("riders.id", ondelete="SET NULL"),
        nullable=True,
    )
    show_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("shows.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    class_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"),
        nullable=True,
    )

    # API IDs (show-specific, for syncing)
    api_entry_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    api_horse_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    api_rider_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    api_class_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    api_ring_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    api_trip_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    api_trainer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Entry-level data
    back_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    order_of_go: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    order_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), default=EntryStatus.ACTIVE.value, nullable=False)
    scratch_trip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gone_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Class-level data (duplicated per entry)
    estimated_start: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actual_start: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    scheduled_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    class_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    total_trips: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_trips: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remaining_trips: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ring_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Results
    placing: Mapped[Optional[int]] = mapped_column(
        "placing",
        Integer,
        nullable=True,
    )
    points_earned: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    total_prize_money: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )

    # Round 1 (Jumpers)
    faults_one: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    time_one: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 3), nullable=True)
    time_fault_one: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    disqualify_status_one: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )

    # Jump off / Round 2 (Jumpers)
    faults_two: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    time_two: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 3), nullable=True)
    time_fault_two: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    disqualify_status_two: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )

    # Hunter scores (6 judges)
    score1: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    score2: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    score3: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    score4: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    score5: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    score6: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)

    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[Optional[datetime]] = ts_updated()

    horse = relationship("Horse", backref="entries")
    rider = relationship("Rider", backref="entries")
    show = relationship("Show", backref="entries")
    event = relationship("Event", backref="entries")
    show_class = relationship("ShowClass", backref="entries")


# -----------------------------------------------------------------------------
# DB operations (session passed by caller)
# -----------------------------------------------------------------------------


async def bulk_upsert_entries(
    session: AsyncSession,
    rows: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """
    Bulk insert/update entries. Each dict has horse_id, rider_id, show_id, event_id,
    class_id, api_entry_id, api_horse_id, api_rider_id, api_class_id, api_ring_id,
    api_trainer_id, back_number, scheduled_date, estimated_start (and optional status/class_status).

    Rows with api_class_id set are upserted on (horse_id, show_id, api_class_id).
    Rows with api_class_id null (no-class / inactive entries) are upserted on (horse_id, show_id).

    Returns:
        (inserted_count, updated_count). Combined counts across both passes.
    """
    if not rows:
        return 0, 0

    with_class = [r for r in rows if r.get("api_class_id") is not None]
    no_class = [r for r in rows if r.get("api_class_id") is None]

    inserted_total = 0
    updated_total = 0

    if with_class:
        key_tuples = [
            (r["horse_id"], r["show_id"], r["api_class_id"])
            for r in with_class
        ]
        result = await session.execute(
            select(Entry.id).where(
                tuple_(Entry.horse_id, Entry.show_id, Entry.api_class_id).in_(key_tuples)
            )
        )
        existing_count = len(result.all())
        inserted_total += len(with_class) - existing_count
        updated_total += existing_count

        stmt = insert(Entry.__table__).values(with_class)
        stmt = stmt.on_conflict_do_update(
            index_elements=["horse_id", "show_id", "api_class_id"],
            index_where=text("api_class_id IS NOT NULL"),
            set_={
                "rider_id": stmt.excluded.rider_id,
                "estimated_start": stmt.excluded.estimated_start,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(stmt)

    if no_class:
        key_tuples_no = [(r["horse_id"], r["show_id"]) for r in no_class]
        result_no = await session.execute(
            select(Entry.id).where(
                and_(
                    tuple_(Entry.horse_id, Entry.show_id).in_(key_tuples_no),
                    Entry.api_class_id.is_(None),
                )
            )
        )
        existing_no_count = len(result_no.all())
        inserted_total += len(no_class) - existing_no_count
        updated_total += existing_no_count

        stmt_no = insert(Entry.__table__).values(no_class)
        stmt_no = stmt_no.on_conflict_do_update(
            index_elements=["horse_id", "show_id"],
            index_where=text("api_class_id IS NULL"),
            set_={
                "rider_id": stmt_no.excluded.rider_id,
                "status": stmt_no.excluded.status,
                "scheduled_date": stmt_no.excluded.scheduled_date,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(stmt_no)

    return inserted_total, updated_total
