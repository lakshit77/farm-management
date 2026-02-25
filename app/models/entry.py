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
    delete,
    func,
    or_,
    select,
    text,
    tuple_,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from app.core.database import Base
from app.core.enums import ClassStatus, EntryStatus
from app.models.base import ts_created, ts_updated, uuid_pk
from app.models.show import Show


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
    Bulk insert/update entries. Responsible solely for upsert (insert + update).

    Each dict must contain horse_id, rider_id, show_id, event_id, class_id,
    api_entry_id, api_horse_id, api_rider_id, api_class_id, api_ring_id,
    api_trainer_id, back_number, scheduled_date, estimated_start (and optional
    status/class_status).

    Rows with api_class_id set are upserted on (horse_id, show_id, api_class_id).
    Rows with api_class_id null (no-class / inactive entries) are upserted on
    (horse_id, show_id).

    Args:
        session: Caller-owned async database session.
        rows: List of entry data dicts to upsert.

    Returns:
        Tuple of (inserted_count, updated_count).
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


async def delete_stale_entries(
    session: AsyncSession,
    rows: List[Dict[str, Any]],
) -> int:
    """
    Delete entries that exist in the DB for the covered (show_id, scheduled_date)
    pairs but are absent from ``rows``.

    Called after ``bulk_upsert_entries`` to remove entries that were present in a
    previous sync but have since been removed from the official source.

    The covered window is derived from the unique (show_id, scheduled_date) pairs
    found in ``rows``. For each such pair, any DB entry whose
    (horse_id, show_id, api_class_id) triple is not represented in ``rows`` is
    considered stale and deleted.

    Args:
        session: Caller-owned async database session.
        rows: The same list of valid entry dicts that was just upserted. Each dict
            must contain horse_id, show_id, scheduled_date, and api_class_id (which
            may be None).

    Returns:
        Number of stale entries deleted.
    """
    if not rows:
        return 0

    # Unique (show_id, scheduled_date) windows covered by this batch.
    covered_pairs: set[Tuple[Any, Any]] = {
        (r["show_id"], r["scheduled_date"])
        for r in rows
        if r.get("show_id") is not None and r.get("scheduled_date") is not None
    }

    if not covered_pairs:
        return 0

    # Surviving (horse_id, show_id, api_class_id) triples from the batch.
    # api_class_id may be None for no-class rows.
    surviving_keys: set[Tuple[Any, Any, Any]] = {
        (r["horse_id"], r["show_id"], r.get("api_class_id"))
        for r in rows
    }

    deleted_total = 0

    for show_id, scheduled_date in covered_pairs:
        # Surviving keys that belong to this show.
        keys_for_show = [
            (horse_id, sid, api_class_id)
            for horse_id, sid, api_class_id in surviving_keys
            if sid == show_id
        ]

        # Fetch all DB entries for this (show_id, scheduled_date).
        fetch_stmt = select(
            Entry.id, Entry.horse_id, Entry.show_id, Entry.api_class_id
        ).where(
            and_(
                Entry.show_id == show_id,
                Entry.scheduled_date == scheduled_date,
            )
        )
        fetch_result = await session.execute(fetch_stmt)
        db_rows = fetch_result.all()

        stale_ids = [
            row.id
            for row in db_rows
            if (row.horse_id, row.show_id, row.api_class_id) not in keys_for_show
        ]

        if stale_ids:
            del_stmt = delete(Entry).where(Entry.id.in_(stale_ids))
            del_result = await session.execute(del_stmt)
            deleted_total += del_result.rowcount

    return deleted_total


async def count_entries_for_farm_on_date(
    session: AsyncSession,
    farm_id: uuid.UUID,
    scheduled_date: date,
) -> int:
    """
    Return the number of entries for the given farm and scheduled date.

    Used to check whether Flow 1 (daily schedule) has run for a date before
    running Flow 2 (class monitoring). Joins Entry to Show to filter by farm_id.

    **Input (request):**
        - session: AsyncSession (caller-owned).
        - farm_id: Farm UUID.
        - scheduled_date: Date to filter (Entry.scheduled_date).

    **Output (response):**
        - Count of entries (>= 0).
    """
    stmt = (
        select(func.count(Entry.id))
        .join(Show, Entry.show_id == Show.id)
        .where(and_(Show.farm_id == farm_id, Entry.scheduled_date == scheduled_date))
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


async def get_active_entries_for_farm_on_date(
    session: AsyncSession,
    farm_id: uuid.UUID,
    scheduled_date: date,
) -> List[Entry]:
    """
    Return entries for the given farm and date that are active (api_class_id set,
    class not completed), with horse, show_class, event, and show loaded.

    Used by Flow 2 (class monitoring) to get active classes and entries. Caller
    groups by (api_class_id, show_id) and dedupes.

    **Input (request):**
        - session: AsyncSession (caller-owned).
        - farm_id: Farm UUID.
        - scheduled_date: Date to filter (Entry.scheduled_date).

    **Output (response):**
        - List of Entry instances with relations loaded.
    """
    stmt = (
        select(Entry)
        .join(Show, Entry.show_id == Show.id)
        .where(
            and_(
                Show.farm_id == farm_id,
                Entry.scheduled_date == scheduled_date,
                Entry.api_class_id.isnot(None),
                or_(
                    Entry.class_status.is_(None),
                    Entry.class_status != ClassStatus.COMPLETED.value,
                ),
            )
        )
        .options(
            selectinload(Entry.horse),
            selectinload(Entry.show_class),
            selectinload(Entry.event),
            selectinload(Entry.show),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def get_entries_for_farm_on_date(
    session: AsyncSession,
    farm_id: uuid.UUID,
    scheduled_date: date,
) -> List[Entry]:
    """
    Return all entries for the given farm and scheduled date, with horse, rider,
    event, show_class, and show loaded.

    Used by schedule view to build nested events → classes → entries. Caller
    may filter by horse_name/class_name and build the view structure.

    **Input (request):**
        - session: AsyncSession (caller-owned).
        - farm_id: Farm UUID.
        - scheduled_date: Date to filter (Entry.scheduled_date).

    **Output (response):**
        - List of Entry instances with relations loaded.
    """
    stmt = (
        select(Entry)
        .join(Show, Entry.show_id == Show.id)
        .where(
            and_(
                Show.farm_id == farm_id,
                Entry.scheduled_date == scheduled_date,
            )
        )
        .options(
            selectinload(Entry.horse),
            selectinload(Entry.rider),
            selectinload(Entry.event),
            selectinload(Entry.show_class),
            selectinload(Entry.show),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def get_horse_remaining_entries_today(
    session: AsyncSession,
    horse_id: uuid.UUID,
    show_id: uuid.UUID,
    completed_entry_id: uuid.UUID,
    scheduled_date: date,
) -> List[Entry]:
    """
    Return the horse's remaining entries for the given show and date: not the
    completed entry, not gone in, class not completed, ordered by estimated_start.

    Used by Flow 3 (horse availability) to compute next class and free time.

    **Input (request):**
        - session: AsyncSession (caller-owned).
        - horse_id: Horse UUID.
        - show_id: Show UUID.
        - completed_entry_id: Entry UUID to exclude (just completed).
        - scheduled_date: Date to filter (Entry.scheduled_date).

    **Output (response):**
        - List of Entry instances with show_class and event loaded, ordered by estimated_start.
    """
    stmt = (
        select(Entry)
        .where(
            Entry.horse_id == horse_id,
            Entry.show_id == show_id,
            Entry.scheduled_date == scheduled_date,
            Entry.id != completed_entry_id,
            Entry.gone_in.is_(False),
            or_(
                Entry.class_status.is_(None),
                Entry.class_status != ClassStatus.COMPLETED.value,
            ),
        )
        .order_by(Entry.estimated_start.asc().nulls_last())
        .options(
            selectinload(Entry.show_class),
            selectinload(Entry.event),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())
