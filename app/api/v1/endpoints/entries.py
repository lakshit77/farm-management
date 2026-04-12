"""All-show entries endpoints: list, toggle selection, trigger daily sync."""

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, cast, func, Integer as SAInteger, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import CUSTOMER_ID
from app.core.database import AsyncSessionLocal, get_async_session
from app.core.enums import EntryStatus
from app.models.entry import Entry, bulk_upsert_entries
from app.models.horse import Horse, bulk_upsert_horses, get_horse_ids_by_names
from app.models.rider import bulk_upsert_riders, get_rider_ids_by_names
from app.models.show import Show
from app.schemas.all_entries import AllEntriesListData, AllEntryItem
from app.schemas.response import ApiResponse, success_response
from app.services.all_entries import sync_all_show_entries
from app.services.schedule import (
    _estimated_start_utc,
    _normalize_class_number,
    _parse_date,
    ensure_farm_and_token,
    resolve_sync_date,
)
from app.services.wellington_client import get_access_token, get_entry_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entries", tags=["entries"])


# ---------------------------------------------------------------------------
# GET /entries/all — paginated list of all show entries
# ---------------------------------------------------------------------------


@router.get(
    "/all",
    response_model=ApiResponse[AllEntriesListData],
    summary="List all show entries",
    description=(
        "Returns all entries for the active show (paginated). "
        "Supports individual filters for horse, rider, trainer, owner, is_own, is_selected."
    ),
)
async def list_all_entries(
    show_id: Optional[str] = Query(None, description="Show UUID. Default: most recent show for farm."),
    horse_name: Optional[str] = Query(None, description="Filter by horse name (case-insensitive, partial match)."),
    rider_name: Optional[str] = Query(None, description="Filter by rider name (case-insensitive, partial match)."),
    trainer_name: Optional[str] = Query(None, description="Filter by trainer name (case-insensitive, partial match)."),
    owner_name: Optional[str] = Query(None, description="Filter by owner name (case-insensitive, partial match)."),
    is_own: Optional[bool] = Query(None, description="Filter: true=own entries, false=non-own, null=all."),
    is_selected: Optional[bool] = Query(None, description="Filter: true=selected, false=unselected, null=all."),
    page: int = Query(1, ge=1, description="Page number."),
    page_size: int = Query(50, ge=10, le=200, description="Results per page."),
    session: AsyncSession = Depends(get_async_session),
) -> ApiResponse[AllEntriesListData]:
    """List all-show entries with individual filters."""
    farm_id, _ = await ensure_farm_and_token(session)

    # Resolve show
    if show_id:
        show = await session.get(Show, show_id)
    else:
        stmt_show = (
            select(Show)
            .where(Show.farm_id == farm_id)
            .order_by(Show.created_at.desc())
            .limit(1)
        )
        result_show = await session.execute(stmt_show)
        show = result_show.scalars().first()

    if not show:
        return success_response(
            data=AllEntriesListData(
                entries=[], total_count=0, page=page, page_size=page_size,
            )
        )

    # Base query: no-class entries (the "roster" rows)
    base_where = [
        Entry.show_id == show.id,
        Entry.api_class_id.is_(None),
    ]

    if is_own is not None:
        base_where.append(Entry.is_own_entry == is_own)

    if is_selected is True:
        base_where.append(Entry.is_selected.is_(True))
    elif is_selected is False:
        base_where.append(Entry.is_selected.is_(False))

    # Individual filters (each is an AND condition)
    needs_horse_join = False
    if horse_name and horse_name.strip():
        base_where.append(Horse.name.ilike(f"%{horse_name.strip()}%"))
        needs_horse_join = True
    if rider_name and rider_name.strip():
        base_where.append(Entry.rider_list_text.ilike(f"%{rider_name.strip()}%"))
    if trainer_name and trainer_name.strip():
        base_where.append(Entry.trainer_name.ilike(f"%{trainer_name.strip()}%"))
    if owner_name and owner_name.strip():
        base_where.append(Entry.owner_name.ilike(f"%{owner_name.strip()}%"))

    # Count query — only join Horse if needed for horse_name filter
    if needs_horse_join:
        count_stmt = (
            select(func.count(Entry.id))
            .join(Horse, Entry.horse_id == Horse.id)
            .where(and_(*base_where))
        )
    else:
        count_stmt = (
            select(func.count(Entry.id))
            .where(and_(*base_where))
        )
    count_result = await session.execute(count_stmt)
    total_count = count_result.scalar() or 0

    # Data query with pagination — numeric sort on back_number
    offset = (page - 1) * page_size
    numeric_back_number = cast(
        func.nullif(func.regexp_replace(Entry.back_number, r'\D', '', 'g'), ''),
        SAInteger,
    )

    if needs_horse_join:
        data_stmt = (
            select(Entry)
            .join(Horse, Entry.horse_id == Horse.id)
            .where(and_(*base_where))
            .options(selectinload(Entry.horse))
            .order_by(numeric_back_number.asc().nulls_last(), Horse.name.asc())
            .offset(offset)
            .limit(page_size)
        )
    else:
        data_stmt = (
            select(Entry)
            .where(and_(*base_where))
            .options(selectinload(Entry.horse))
            .order_by(numeric_back_number.asc().nulls_last(), Entry.back_number.asc().nulls_last())
            .offset(offset)
            .limit(page_size)
        )

    data_result = await session.execute(data_stmt)
    entries = list(data_result.scalars().unique().all())

    items = [
        AllEntryItem(
            id=str(e.id),
            horse_name=e.horse.name if e.horse else "Unknown",
            horse_id=str(e.horse_id),
            back_number=e.back_number,
            rider_list=e.rider_list_text,
            trainer_name=e.trainer_name,
            owner_name=e.owner_name,
            is_own_entry=e.is_own_entry,
            is_selected=e.is_selected,
            status=e.status,
            api_entry_id=e.api_entry_id,
        )
        for e in entries
    ]

    return success_response(
        data=AllEntriesListData(
            entries=items,
            total_count=total_count,
            page=page,
            page_size=page_size,
            show_id=str(show.id),
            show_name=show.name,
        )
    )


# ---------------------------------------------------------------------------
# PATCH /entries/{entry_id}/select — toggle monitoring selection
# ---------------------------------------------------------------------------


@router.patch(
    "/{entry_id}/select",
    response_model=ApiResponse[dict[str, Any]],
    summary="Toggle entry selection for monitoring",
    description=(
        "Select (true): sets is_selected=true immediately and returns. If no class-level "
        "rows exist yet, fetches entry details from Wellington API in the background. "
        "Unselect (false): sets is_selected=false on all entry rows for this horse/show."
    ),
)
async def toggle_entry_selection(
    entry_id: str,
    selected: bool = Query(..., description="true=activate monitoring, false=deactivate"),
) -> ApiResponse[dict[str, Any]]:
    """Toggle an entry's is_selected flag. Returns immediately; detail fetch runs in background."""
    async with AsyncSessionLocal() as session:
        entry = await session.get(Entry, entry_id)
        if not entry:
            return success_response(data={"error": "Entry not found"})

        if not selected:
            # Unselect: set is_selected=false on all entries for this api_entry_id
            if entry.api_entry_id:
                stmt = (
                    select(Entry)
                    .where(
                        and_(
                            Entry.api_entry_id == entry.api_entry_id,
                            Entry.show_id == entry.show_id,
                        )
                    )
                )
                result = await session.execute(stmt)
                related_entries = list(result.scalars().all())
                for e in related_entries:
                    e.is_selected = False
                    session.add(e)
            else:
                entry.is_selected = False
                session.add(entry)

            await session.commit()
            return success_response(data={
                "entry_id": str(entry.id),
                "selected": False,
            })

        # Select: set is_selected=true on all existing rows immediately
        needs_detail_fetch = False

        if entry.api_entry_id:
            stmt = (
                select(Entry)
                .where(
                    and_(
                        Entry.api_entry_id == entry.api_entry_id,
                        Entry.show_id == entry.show_id,
                    )
                )
            )
            result = await session.execute(stmt)
            related_entries = list(result.scalars().all())
            for e in related_entries:
                e.is_selected = True
                session.add(e)

            has_class_rows = any(e.api_class_id is not None for e in related_entries)
            if not has_class_rows:
                needs_detail_fetch = True
        else:
            entry.is_selected = True
            session.add(entry)

        # Capture values needed for the background task before committing
        bg_entry_id = str(entry.id)
        bg_api_entry_id = entry.api_entry_id
        bg_show_id = entry.show_id
        bg_is_own_entry = entry.is_own_entry

        await session.commit()

        # Fire background task if class-level rows need to be created
        if needs_detail_fetch and bg_api_entry_id:
            asyncio.create_task(
                _fetch_and_create_class_rows(
                    bg_entry_id, bg_api_entry_id, bg_show_id, bg_is_own_entry,
                )
            )

        return success_response(data={
            "entry_id": bg_entry_id,
            "selected": True,
        })


async def _fetch_and_create_class_rows(
    entry_id: str,
    api_entry_id: int,
    show_id: Any,
    is_own_entry: bool,
) -> None:
    """Background task: fetch entry detail from Wellington API and create class-level rows."""
    try:
        async with AsyncSessionLocal() as session:
            show = await session.get(Show, show_id) if show_id else None
            if not show or not show.api_show_id:
                logger.warning("Background detail fetch: cannot resolve show for entry %s", entry_id)
                return

            farm_id = show.farm_id
            customer_id_str = (CUSTOMER_ID or "").strip() or "15"
            token = await get_access_token()

            entry_detail = await get_entry_detail(
                api_entry_id, show.api_show_id, customer_id_str, token=token
            )

            entry_obj = entry_detail.get("entry") or {}
            horse_name = (entry_obj.get("horse") or "").strip()
            api_horse_id = entry_obj.get("horse_id")
            api_trainer_id = entry_obj.get("trainer_id")
            back_number = str(entry_obj.get("number", "")).strip() or None
            entry_riders = entry_detail.get("entry_riders") or []
            classes_list = entry_detail.get("classes") or []

            # Ensure horse exists
            if horse_name:
                await bulk_upsert_horses(session, farm_id, [horse_name])
            horse_id_list = await get_horse_ids_by_names(
                session, farm_id, [horse_name] if horse_name else []
            )
            horse_name_to_id = {n: i for i, n in horse_id_list}

            # Resolve horse_id — fall back to the roster row's horse_id
            horse_id = horse_name_to_id.get(horse_name)
            if not horse_id:
                roster_entry = await session.get(Entry, entry_id)
                horse_id = roster_entry.horse_id if roster_entry else None
            if not horse_id:
                logger.warning("Background detail fetch: cannot resolve horse for entry %s", entry_id)
                return

            # Ensure riders exist
            rider_names = set()
            for er in entry_riders:
                rn = (er.get("rider_name") or "").strip()
                if rn:
                    rider_names.add(rn)
            for cl in classes_list:
                rn = (cl.get("rider_name") or "").strip()
                if rn:
                    rider_names.add(rn)
            if rider_names:
                await bulk_upsert_riders(session, farm_id, list(rider_names))
            rider_id_list = await get_rider_ids_by_names(
                session, farm_id, list(rider_names)
            )
            rider_name_to_id = {n: i for i, n in rider_id_list}

            default_rider = (
                (entry_riders[0].get("rider_name") or "") if entry_riders else ""
            )

            from app.models.show_class import bulk_upsert_classes, get_classes_by_farm_keys  # noqa: PLC0415
            from app.models.event import get_events_by_farm_for_rings  # noqa: PLC0415

            class_keys = []
            for cl in classes_list:
                cname = (cl.get("name") or "").strip()
                if not cname:
                    continue
                cnum = _normalize_class_number(cl.get("class_number"))
                class_keys.append((cname, cnum))

            if class_keys:
                await bulk_upsert_classes(
                    session, farm_id,
                    [(name, cnum, None, None, None) for name, cnum in class_keys],
                )
            existing_classes = await get_classes_by_farm_keys(session, farm_id, class_keys)
            name_cnum_to_class_id = {(r[1], r[2]): r[0] for r in existing_classes}

            event_list = await get_events_by_farm_for_rings(session, farm_id)
            ring_number_to_event_id = {}
            for eid, _ename, rnum in event_list:
                if rnum is not None:
                    ring_number_to_event_id[rnum] = eid

            new_rows = []
            for cl in classes_list:
                cname = (cl.get("name") or "").strip()
                if not cname:
                    continue
                cnum = _normalize_class_number(cl.get("class_number"))
                class_uuid = name_cnum_to_class_id.get((cname, cnum))
                if not class_uuid:
                    continue

                ring_num = cl.get("ring")
                event_uuid = ring_number_to_event_id.get(ring_num) if ring_num is not None else None
                scheduled_date_str = cl.get("scheduled_date")
                schedule_starttime = cl.get("schedule_starttime")
                estimated_start = _estimated_start_utc(scheduled_date_str, schedule_starttime)
                sdate = _parse_date(scheduled_date_str)
                rn = (cl.get("rider_name") or "").strip()
                rider_id = rider_name_to_id.get(rn or default_rider)

                new_rows.append({
                    "horse_id": horse_id,
                    "rider_id": rider_id,
                    "show_id": show.id,
                    "event_id": event_uuid,
                    "class_id": class_uuid,
                    "api_entry_id": api_entry_id,
                    "api_horse_id": api_horse_id,
                    "api_rider_id": cl.get("rider_id"),
                    "api_class_id": cl.get("class_id"),
                    "api_ring_id": ring_num,
                    "api_trainer_id": api_trainer_id,
                    "back_number": back_number,
                    "scheduled_date": sdate,
                    "estimated_start": estimated_start,
                    "status": EntryStatus.ACTIVE.value,
                    "class_status": None,
                    "is_own_entry": is_own_entry,
                    "is_selected": True,
                })

            if new_rows:
                await bulk_upsert_entries(session, new_rows)

            await session.commit()
            logger.info(
                "Background detail fetch complete: entry=%s classes_created=%d",
                entry_id, len(new_rows),
            )

    except Exception:
        logger.exception("Background detail fetch failed for entry %s", entry_id)


# ---------------------------------------------------------------------------
# POST /entries/sync-all — trigger all-entries daily sync
# ---------------------------------------------------------------------------


@router.post(
    "/sync-all",
    response_model=ApiResponse[dict[str, Any]],
    summary="Sync all show entries",
    description="Fetches all entries for the active show from Wellington API and stores them. Called by n8n daily after Flow 1.",
)
async def sync_all_entries_endpoint(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD (UTC). Default: today UTC."),
) -> ApiResponse[dict[str, Any]]:
    """Trigger the all-show-entries sync."""
    data = await sync_all_show_entries(date_override=date)
    return success_response(data=data)
