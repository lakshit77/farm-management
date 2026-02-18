"""
Schedule view service: load entries for a date and return nested events → classes → entries
with horse, rider, and backend status for the front-end.
"""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import CUSTOMER_ID, FARM_NAME
from app.core.enums import EntryStatus
from app.models.entry import Entry
from app.models.event import Event
from app.models.farm import get_farm_by_name_and_customer
from app.models.horse import Horse
from app.models.rider import Rider
from app.models.show import Show
from app.models.show_class import ShowClass
from app.schemas.schedule_view import (
    ClassView,
    EntryView,
    EventView,
    HorseView,
    RiderView,
    ScheduleViewData,
)


def _parse_customer_id(value: Any) -> Optional[int]:
    """Parse customer_id to Optional[int] for DB lookup."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _uuid_str(u: Any) -> str:
    """Convert UUID to string for JSON."""
    return str(u) if u is not None else ""


def _date_str(d: Optional[date]) -> Optional[str]:
    """Format date as YYYY-MM-DD."""
    return d.isoformat() if d else None


async def get_schedule_view(
    session: AsyncSession,
    view_date: date,
) -> ScheduleViewData:
    """
    Load schedule for the given date: events (rings) with classes and entries.
    Each entry includes horse, rider, and all backend status fields.
    Scoped by farm (FARM_NAME, CUSTOMER_ID from env).
    """
    cid = _parse_customer_id(CUSTOMER_ID)
    farm = await get_farm_by_name_and_customer(session, FARM_NAME, cid)
    if farm is None:
        return ScheduleViewData(date=view_date.isoformat(), events=[])

    # Load all entries for this date with show.farm_id = farm.id, and relations
    stmt = (
        select(Entry)
        .join(Show, Entry.show_id == Show.id)
        .where(
            and_(
                Show.farm_id == farm.id,
                Entry.scheduled_date == view_date,
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
    entries = list(result.scalars().unique())

    # Build nested structure: event_id -> class_id -> [entries]
    by_event: Dict[str, Dict[str, List[Entry]]] = {}
    show_name: Optional[str] = None
    show_id: Optional[str] = None

    for e in entries:
        event = e.event
        show_class = e.show_class
        if e.show:
            show_name = e.show.name
            show_id = _uuid_str(e.show.id)
        if event is None or show_class is None:
            continue
        eid = _uuid_str(event.id)
        cid_key = _uuid_str(show_class.id)
        if eid not in by_event:
            by_event[eid] = {}
        if cid_key not in by_event[eid]:
            by_event[eid][cid_key] = []
        by_event[eid][cid_key].append(e)

    # Sort entries within each class by order_of_go
    for eid in by_event:
        for cid_key in by_event[eid]:
            by_event[eid][cid_key].sort(
                key=lambda x: (x.order_of_go is None, x.order_of_go or 0)
            )

    # Build event -> class -> entry view models
    events_out: List[EventView] = []
    event_objs: Dict[str, Event] = {_uuid_str(e.event.id): e.event for e in entries if e.event}
    class_objs: Dict[str, ShowClass] = {
        _uuid_str(e.show_class.id): e.show_class for e in entries if e.show_class
    }

    for eid, classes_dict in by_event.items():
        event = event_objs.get(eid)
        if not event:
            continue
        classes_out: List[ClassView] = []
        for cid_key, entry_list in classes_dict.items():
            show_class = class_objs.get(cid_key)
            if not show_class:
                continue
            entry_views = [_entry_to_view(e) for e in entry_list]
            classes_out.append(
                ClassView(
                    id=_uuid_str(show_class.id),
                    name=show_class.name,
                    class_number=show_class.class_number,
                    sponsor=show_class.sponsor,
                    prize_money=show_class.prize_money,
                    class_type=show_class.class_type,
                    entries=entry_views,
                )
            )
        # Sort classes by class_number or name
        classes_out.sort(key=lambda c: (c.class_number or "", c.name))
        events_out.append(
            EventView(
                id=eid,
                name=event.name,
                ring_number=event.ring_number,
                classes=classes_out,
            )
        )

    events_out.sort(key=lambda ev: (ev.ring_number is None, ev.ring_number or 0, ev.name))

    return ScheduleViewData(
        date=view_date.isoformat(),
        show_name=show_name,
        show_id=show_id,
        events=events_out,
    )


def _entry_to_view(e: Entry) -> EntryView:
    """Build EntryView from Entry ORM with horse and rider."""
    horse = e.horse
    rider = e.rider
    return EntryView(
        id=_uuid_str(e.id),
        horse=HorseView(
            id=_uuid_str(horse.id) if horse else "",
            name=horse.name if horse else "",
            status=horse.status if horse else EntryStatus.ACTIVE.value,
        ),
        rider=RiderView(id=_uuid_str(rider.id), name=rider.name) if rider else None,
        back_number=e.back_number,
        order_of_go=e.order_of_go,
        order_total=e.order_total,
        status=e.status or EntryStatus.ACTIVE.value,
        scratch_trip=e.scratch_trip or False,
        gone_in=e.gone_in or False,
        estimated_start=e.estimated_start,
        actual_start=e.actual_start,
        scheduled_date=_date_str(e.scheduled_date),
        class_status=e.class_status,
        ring_status=e.ring_status,
        total_trips=e.total_trips,
        completed_trips=e.completed_trips,
        remaining_trips=e.remaining_trips,
        placing=e.placing,
        points_earned=e.points_earned,
        total_prize_money=e.total_prize_money,
        faults_one=e.faults_one,
        time_one=e.time_one,
        disqualify_status_one=e.disqualify_status_one,
        faults_two=e.faults_two,
        time_two=e.time_two,
        disqualify_status_two=e.disqualify_status_two,
        score1=e.score1,
        score2=e.score2,
        score3=e.score3,
        score4=e.score4,
        score5=e.score5,
        score6=e.score6,
    )
