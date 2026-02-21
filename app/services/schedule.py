"""
Schedule-related business logic (daily job steps).

Flow 1: Morning Sync — modular steps: resolve date, ensure farm, fetch schedule,
upsert show/events/classes, fetch entries and details, upsert horses/riders/entries,
build summary. One DB session; bulk ops where possible.
Step 9 (Telegram) is skipped; summary is returned in the API response.
"""

import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple, TypedDict, Union

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CUSTOMER_ID, FARM_NAME
from app.core.database import AsyncSessionLocal
from app.core.enums import EntryStatus, ScheduleTaskResult, ScheduleTriggerType
from app.models.entry import bulk_upsert_entries
from app.models.event import bulk_upsert_events, get_events_by_farm_for_rings
from app.models.farm import Farm, create_farm, get_farm_by_name_and_customer
from app.models.horse import bulk_upsert_horses, get_horse_ids_by_names
from app.models.rider import bulk_upsert_riders, get_rider_ids_by_names
from app.models.show import upsert_show
from app.models.show_class import bulk_upsert_classes, get_classes_by_farm_keys
from app.core.logging_config import SCHEDULE_DAILY_LOGGER_NAME
from app.services.wellington_client import (
    WellingtonAPIError,
    get_access_token,
    get_entry_detail,
    get_entries_my,
    get_schedule,
)

# Daily schedule logs go to logs/schedule_daily.log (see app/core/logging_config.py)
logger = logging.getLogger(SCHEDULE_DAILY_LOGGER_NAME)

ENTRY_DETAIL_BATCH_SIZE = 10


# -----------------------------------------------------------------------------
# Summary counts (nested structure for API/DB insertion and update counts)
# -----------------------------------------------------------------------------


class _EntityCounts(TypedDict, total=False):
    """Counts for a single entity type: from_api, inserted, updated."""

    from_api: int
    inserted: int
    updated: int


class _EntryCounts(TypedDict, total=False):
    """Entry-specific counts including detail/row stages."""

    from_api: int
    entry_details_fetched: int
    entry_rows_built: int
    inserted: int
    updated: int


def _entity_counts(
    from_api: int = 0,
    inserted: int = 0,
    updated: int = 0,
) -> _EntityCounts:
    """Build a consistent entity-counts dict for rings, classes, horses, riders."""
    return {"from_api": from_api, "inserted": inserted, "updated": updated}


def _entry_counts(
    from_api: int = 0,
    entry_details_fetched: int = 0,
    entry_rows_built: int = 0,
    inserted: int = 0,
    updated: int = 0,
) -> _EntryCounts:
    """Build entry-stage counts for summary."""
    return {
        "from_api": from_api,
        "entry_details_fetched": entry_details_fetched,
        "entry_rows_built": entry_rows_built,
        "inserted": inserted,
        "updated": updated,
    }


# -----------------------------------------------------------------------------
# Private helpers (parsing / formatting)
# -----------------------------------------------------------------------------


def _parse_customer_id(value: Union[str, int, None]) -> Optional[int]:
    """Parse customer_id from env (str) or int to Optional[int] for DB."""
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


def _parse_date(s: Optional[str]) -> Optional[date]:
    """Parse ISO date or datetime string to date (UTC)."""
    if not s:
        return None
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.date()
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _normalize_class_number(value: Any) -> Optional[str]:
    """Normalize API class_number to Optional[str] for (name, class_number) lookup."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _estimated_start_utc(
    scheduled_date_str: Optional[str],
    schedule_starttime: Optional[str],
) -> Optional[str]:
    """Combine scheduled_date (ISO) + schedule_starttime to UTC datetime string."""
    if not scheduled_date_str or not schedule_starttime:
        return None
    d = _parse_date(scheduled_date_str)
    if not d:
        return None
    parts = schedule_starttime.strip().split(".")
    time_part = parts[0].strip()
    try:
        h, m, s = (int(x) for x in time_part.split(":")[:3])
    except (ValueError, TypeError):
        return None
    dt = datetime(d.year, d.month, d.day, h, m, s, tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# -----------------------------------------------------------------------------
# Public: farm (reused by Flow 1)
# -----------------------------------------------------------------------------


async def get_or_create_farm(
    session: AsyncSession,
    farm_name: str,
    customer_id: Union[str, int, None],
) -> Farm:
    """
    Get a farm by name and customer_id, or create it if it does not exist.

    **Input (request):**
        - session: AsyncSession (caller-owned).
        - farm_name: Farm display name.
        - customer_id: API customer id (str or int); normalized for DB.

    **Output (response):**
        - Farm: existing or newly created instance. Caller must commit the session.

    **What it does:** Looks up by (name, customer_id); if missing, creates the farm and returns it.
    """
    cid = _parse_customer_id(customer_id)
    existing = await get_farm_by_name_and_customer(session, farm_name, cid)
    if existing is not None:
        return existing
    return await create_farm(session, name=farm_name, customer_id=cid)


# -----------------------------------------------------------------------------
# Flow 1 – Step 0: Resolve sync date
# -----------------------------------------------------------------------------


def resolve_sync_date(date_override: Optional[str]) -> Tuple[str, date]:
    """
    Resolve the sync date to a string and date object in UTC.

    **Input (request):**
        - date_override: Optional "YYYY-MM-DD". If None or invalid, uses today UTC.

    **Output (response):**
        - (sync_date_str, sync_date): e.g. ("2026-02-13", date(2026, 2, 13)).

    **What it does:** Validates/normalizes date_override; falls back to today in UTC.
    """
    if date_override:
        sync_date_str = date_override.strip()[:10]
        try:
            sync_date = datetime.strptime(sync_date_str, "%Y-%m-%d").date()
        except ValueError:
            sync_date = datetime.now(timezone.utc).date()
            sync_date_str = sync_date.strftime("%Y-%m-%d")
    else:
        sync_date = datetime.now(timezone.utc).date()
        sync_date_str = sync_date.strftime("%Y-%m-%d")
    return sync_date_str, sync_date


# -----------------------------------------------------------------------------
# Flow 1 – Step: Ensure farm and token
# -----------------------------------------------------------------------------


async def ensure_farm_and_token(
    session: AsyncSession,
) -> Tuple[Any, str]:
    """
    Ensure the farm exists and obtain a Wellington API token for this run.

    **Input (request):**
        - session: AsyncSession (caller-owned).

    **Output (response):**
        - farm_id: UUID of the farm (from get_or_create_farm).
        - token: Bearer token string for Wellington API calls.

    **What it does:** Calls get_or_create_farm(FARM_NAME, CUSTOMER_ID), then get_access_token().
    """
    farm = await get_or_create_farm(session, FARM_NAME, CUSTOMER_ID)
    token = await get_access_token()
    return farm.id, token


# -----------------------------------------------------------------------------
# Flow 1 – Steps 1–2: Fetch schedule and upsert show
# -----------------------------------------------------------------------------


async def fetch_schedule_and_upsert_show(
    session: AsyncSession,
    farm_id: Any,
    sync_date_str: str,
    customer_id_str: str,
    token: str,
) -> Tuple[
    Any, str, int, List[dict], Optional[date], Optional[date], int, int
]:
    """
    Fetch the daily schedule from Wellington API and upsert the show in the DB.

    **Input (request):**
        - session: AsyncSession.
        - farm_id: Farm UUID.
        - sync_date_str: Date "YYYY-MM-DD" for the schedule request.
        - customer_id_str: Customer ID string for the API.
        - token: Wellington Bearer token.

    **Output (response):**
        - show_uuid: UUID of the show (inserted or updated).
        - show_name: Display name of the show.
        - api_show_id: External show ID from the API.
        - rings_data: List of ring dicts from the schedule (ring_name, ring_number, classes, etc.).
        - start_date: Parsed show start date or None.
        - end_date: Parsed show end date or None.
        - show_inserted: 1 if show was inserted, 0 otherwise.
        - show_updated: 1 if show was updated (already existed), 0 otherwise.

    **What it does:** GET /schedule, parse show and rings; upsert show by (farm_id, api_show_id); return show id and raw rings for downstream steps.
    """
    schedule_data = await get_schedule(sync_date_str, customer_id_str, token=token)
    show_data = schedule_data.get("show") or {}
    rings_data = schedule_data.get("rings") or []
    api_show_id = show_data.get("show_id")
    show_name = (show_data.get("show_name") or "").strip() or "Unknown Show"
    start_date = _parse_date(show_data.get("start_date"))
    end_date = _parse_date(show_data.get("end_date"))

    if not api_show_id:
        raise WellingtonAPIError("Schedule response missing show_id")

    show_uuid, show_inserted, show_updated = await upsert_show(
        session, farm_id, api_show_id, show_name, start_date, end_date
    )
    return (
        show_uuid,
        show_name,
        api_show_id,
        rings_data,
        start_date,
        end_date,
        show_inserted,
        show_updated,
    )


# -----------------------------------------------------------------------------
# Flow 1 – Step 3: Upsert events (rings) and build ring_number → event_id map
# -----------------------------------------------------------------------------


async def upsert_events_and_build_ring_map(
    session: AsyncSession,
    farm_id: Any,
    rings_data: List[dict],
) -> Tuple[Dict[int, Any], int, int]:
    """
    Bulk upsert events (rings) and return a mapping from ring_number to event UUID and counts.

    **Input (request):**
        - session: AsyncSession.
        - farm_id: Farm UUID.
        - rings_data: List of ring dicts from schedule (ring_name, ring_number).

    **Output (response):**
        - ring_number_to_event_id: Dict[ring_number, event_uuid]. Used to set event_id on entries.
        - events_inserted: Number of event rows inserted.
        - events_updated: Number of event rows updated (0 when using DO NOTHING).

    **What it does:** Bulk insert/update events on (farm_id, name); then select events for this farm to build ring_number → id.
    """
    event_rows = [(r.get("ring_name") or "", r.get("ring_number")) for r in rings_data]
    events_inserted, events_updated = await bulk_upsert_events(
        session, farm_id, event_rows
    )
    event_list = await get_events_by_farm_for_rings(session, farm_id)
    ring_number_to_event_id: Dict[int, Any] = {}
    for eid, _ename, rnum in event_list:
        if rnum is not None:
            ring_number_to_event_id[rnum] = eid
    return ring_number_to_event_id, events_inserted, events_updated


# -----------------------------------------------------------------------------
# Flow 1 – Step 4: Upsert classes and build api_class_id → class_id map
# -----------------------------------------------------------------------------


async def upsert_classes_and_build_class_map(
    session: AsyncSession,
    farm_id: Any,
    rings_data: List[dict],
) -> Tuple[Dict[int, Any], int, int, int]:
    """
    Bulk upsert classes (deduped by api_class_id) and return api_class_id → class UUID and counts.

    **Input (request):**
        - session: AsyncSession.
        - farm_id: Farm UUID.
        - rings_data: List of ring dicts, each with "classes" list (class_id, class_name, class_number, sponsor, etc.).

    **Output (response):**
        - api_class_id_to_class_id: Dict[api_class_id, class_uuid]. Used to set class_id on entries.
        - classes_from_api: Number of distinct classes from API (deduped).
        - classes_inserted: Number of class rows inserted.
        - classes_updated: Number of class rows updated (0 when using DO NOTHING).

    **What it does:** Dedupes classes by class_id, bulk upserts by (farm_id, name, class_number), then selects to build api_class_id → id.
    """
    class_keys: List[Tuple[int, str, Optional[str], Optional[str], Optional[Decimal], Optional[str]]] = []
    seen_class_ids: Set[int] = set()
    for ring in rings_data:
        for c in ring.get("classes") or []:
            cid = c.get("class_id")
            if cid is None or cid in seen_class_ids:
                continue
            # Only process classes that have a name and at least one trip (valid class)
            cname = (c.get("class_name") or "").strip()
            total_trips = c.get("total_trips")
            try:
                total_trips_val = int(total_trips) if total_trips is not None else 0
            except (TypeError, ValueError):
                total_trips_val = 0
            if not cname or total_trips_val <= 0:
                continue
            seen_class_ids.add(cid)
            cnum = (
                str(c.get("class_number", "")).strip()
                if c.get("class_number") is not None
                else None
            )
            sponsor = (c.get("sponsor") or "").strip() or None
            prize = c.get("prize_money")
            if prize is not None and not isinstance(prize, Decimal):
                try:
                    prize = Decimal(str(prize))
                except Exception:
                    prize = None
            ctype = (c.get("class_type") or "").strip() or None
            class_keys.append((cid, cname, cnum, sponsor, prize, ctype))

    classes_from_api = len(class_keys)
    classes_inserted, classes_updated = 0, 0
    class_rows = [
        (cname, cnum, sponsor, prize, ctype)
        for _, cname, cnum, sponsor, prize, ctype in class_keys
    ]
    if class_rows:
        classes_inserted, classes_updated = await bulk_upsert_classes(
            session, farm_id, class_rows
        )

    keys_for_select = [(cname, cnum) for _, cname, cnum, *_ in class_keys]
    class_id_list = await get_classes_by_farm_keys(session, farm_id, keys_for_select)
    name_cnum_to_id: Dict[Tuple[str, Optional[str]], Any] = {
        (r[1], r[2]): r[0] for r in class_id_list
    }
    api_class_id_to_class_id: Dict[int, Any] = {}
    for api_cid, cname, cnum, *_ in class_keys:
        api_class_id_to_class_id[api_cid] = name_cnum_to_id.get((cname, cnum))

    return (
        api_class_id_to_class_id,
        classes_from_api,
        classes_inserted,
        classes_updated,
    )


# -----------------------------------------------------------------------------
# Flow 1 – Steps 5–6: Get my entries and fetch entry details in batches
# -----------------------------------------------------------------------------


async def fetch_entry_details(
    api_show_id: int,
    customer_id_str: str,
    token: str,
    entries_list: List[dict],
) -> List[dict]:
    """
    Fetch full details for each entry from the Wellington API in batches.

    **Input (request):**
        - api_show_id: External show ID.
        - customer_id_str: Customer ID string.
        - token: Wellington Bearer token.
        - entries_list: List of entry summaries from GET /entries/my (entry_id, horse, number, etc.).

    **Output (response):**
        - List of entry-detail dicts (entry, classes, entry_riders). Failed fetches are skipped and logged.

    **What it does:** For each entry_id, GET /entries/{entry_id}; runs in batches of ENTRY_DETAIL_BATCH_SIZE with asyncio.gather.
    """
    entry_details: List[dict] = []
    for i in range(0, len(entries_list), ENTRY_DETAIL_BATCH_SIZE):
        batch = entries_list[i : i + ENTRY_DETAIL_BATCH_SIZE]
        tasks = [
            get_entry_detail(e.get("entry_id"), api_show_id, customer_id_str, token=token)
            for e in batch
            if e.get("entry_id") is not None
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Entry detail failed: %s", r)
                continue
            entry_details.append(r)
    return entry_details


async def get_or_create_class_map_from_entry_details(
    session: AsyncSession,
    farm_id: Any,
    entry_details: List[dict],
) -> Dict[Tuple[str, Optional[str]], Any]:
    """
    Build (class_name, class_number) -> class UUID map from entry details.
    Ensures every class referenced in entry details exists in the classes table
    (get-or-create by name + class_number) so entries never get class_id = NULL.

    **Input (request):**
        - session: AsyncSession (caller-owned).
        - farm_id: Farm UUID.
        - entry_details: List of entry-detail dicts (entry, classes, entry_riders).

    **Output (response):**
        - Map (class_name, class_number) -> class UUID. Keys use normalized name and class_number.
    """
    keys_set: Set[Tuple[str, Optional[str]]] = set()
    for ed in entry_details:
        for cl in ed.get("classes") or []:
            name = (cl.get("name") or "").strip()
            if not name:
                continue
            cnum = _normalize_class_number(cl.get("class_number"))
            keys_set.add((name, cnum))
    keys_list = list(keys_set)
    if not keys_list:
        return {}

    existing = await get_classes_by_farm_keys(session, farm_id, keys_list)
    name_cnum_to_id: Dict[Tuple[str, Optional[str]], Any] = {
        (r[1], r[2]): r[0] for r in existing
    }
    missing = [(n, c) for n, c in keys_list if (n, c) not in name_cnum_to_id]
    if missing:
        await bulk_upsert_classes(
            session,
            farm_id,
            [(name, cnum, None, None, None) for name, cnum in missing],
        )
        existing_after = await get_classes_by_farm_keys(session, farm_id, keys_list)
        name_cnum_to_id = {(r[1], r[2]): r[0] for r in existing_after}
    return name_cnum_to_id


# -----------------------------------------------------------------------------
# Flow 1 – Build entry rows and collect horses/riders/time–ring list
# -----------------------------------------------------------------------------


def build_entry_rows_and_collect_entities(
    entry_details: List[dict],
    rings_data: List[dict],
    show_uuid: Any,
    ring_number_to_event_id: Dict[int, Any],
    name_class_number_to_class_id: Dict[Tuple[str, Optional[str]], Any],
    sync_date: Optional[date] = None,
) -> Tuple[List[Dict[str, Any]], Set[str], Set[str], List[Tuple[str, str]]]:
    """
    From entry details, build DB entry rows (with _horse_name / _rider_name placeholders) and collect unique horses, riders, and (time, ring_name) for summary.

    Resolves class_id by (class_name, class_number) from entry details so we never create entries with class_id = NULL (no "Unknown Class").

    **Input (request):**
        - entry_details: List of entry-detail dicts (entry, classes, entry_riders).
        - rings_data: Ring list from schedule (for ring_number → ring_name).
        - show_uuid: Show UUID.
        - ring_number_to_event_id: Map from ring number to event UUID.
        - name_class_number_to_class_id: Map (class_name, class_number) -> class UUID (from get_or_create_class_map_from_entry_details).
        - sync_date: Optional date for the show day; used as scheduled_date for entries with no class.

    **Output (response):**
        - entry_rows: List of dicts suitable for bulk_upsert_entries; each has _horse_name and _rider_name (to be resolved to UUIDs later).
        - horse_names: Set of horse names seen.
        - rider_names: Set of rider names seen.
        - time_ring_list: List of (estimated_start_utc_str, ring_name) for first/last class summary.

    **What it does:** Iterates entry_details and each entry's classes; resolves class_id by (name, class_number); builds one row per (entry, class) only when class is found; for entries with no classes, builds one row with status INACTIVE. Collects horse/rider names and (time, ring_name).
    """
    horse_names: Set[str] = set()
    rider_names: Set[str] = set()
    entry_rows: List[Dict[str, Any]] = []
    time_ring_list: List[Tuple[str, str]] = []

    ring_number_to_name: Dict[int, str] = {
        r.get("ring_number"): (r.get("ring_name") or "")
        for r in rings_data
        if r.get("ring_number") is not None
    }

    for ed in entry_details:
        entry_obj = ed.get("entry") or {}
        api_entry_id = entry_obj.get("entry_id")
        api_horse_id = entry_obj.get("horse_id")
        horse_name = (entry_obj.get("horse") or "").strip()
        back_number = str(entry_obj.get("number", "")).strip() or None
        api_trainer_id = entry_obj.get("trainer_id")
        if horse_name:
            horse_names.add(horse_name)
        entry_riders = ed.get("entry_riders") or []
        for er in entry_riders:
            rn = (er.get("rider_name") or "").strip()
            if rn:
                rider_names.add(rn)
        classes_list = ed.get("classes") or []
        default_rider = (
            (entry_riders[0].get("rider_name") or "") if entry_riders else ""
        )
        api_rider_id_first = (
            entry_riders[0].get("rider_id") if entry_riders else None
        )
        for cl in classes_list:
            rn = (cl.get("rider_name") or "").strip()
            if rn:
                rider_names.add(rn)
            ring_num = cl.get("ring")
            scheduled_date_str = cl.get("scheduled_date")
            schedule_starttime = cl.get("schedule_starttime")
            estimated_start = _estimated_start_utc(scheduled_date_str, schedule_starttime)
            ring_name = (
                ring_number_to_name.get(ring_num, "") if ring_num is not None else ""
            )
            if estimated_start and ring_name:
                time_ring_list.append((estimated_start, ring_name))
            class_name = (cl.get("name") or "").strip()
            class_number = _normalize_class_number(cl.get("class_number"))
            if not class_name:
                continue
            class_uuid = name_class_number_to_class_id.get((class_name, class_number))
            if class_uuid is None:
                continue
            api_class_id = cl.get("class_id")
            event_uuid = (
                ring_number_to_event_id.get(ring_num) if ring_num is not None else None
            )
            sdate = _parse_date(scheduled_date_str)
            entry_rows.append({
                "horse_id": None,
                "rider_id": None,
                "show_id": show_uuid,
                "event_id": event_uuid,
                "class_id": class_uuid,
                "api_entry_id": api_entry_id,
                "api_horse_id": api_horse_id,
                "api_rider_id": cl.get("rider_id"),
                "api_class_id": api_class_id,
                "api_ring_id": ring_num,
                "api_trainer_id": api_trainer_id,
                "back_number": back_number,
                "scheduled_date": sdate,
                "estimated_start": estimated_start,
                "status": EntryStatus.ACTIVE.value,
                "class_status": None,
                "_horse_name": horse_name,
                "_rider_name": rn or default_rider,
            })
        # If this entry has no classes, add one row with status INACTIVE so the horse appears in entries table
        if not classes_list and horse_name:
            entry_rows.append({
                "horse_id": None,
                "rider_id": None,
                "show_id": show_uuid,
                "event_id": None,
                "class_id": None,
                "api_entry_id": api_entry_id,
                "api_horse_id": api_horse_id,
                "api_rider_id": api_rider_id_first,
                "api_class_id": None,
                "api_ring_id": None,
                "api_trainer_id": api_trainer_id,
                "back_number": back_number,
                "scheduled_date": sync_date,
                "estimated_start": None,
                "status": EntryStatus.INACTIVE.value,
                "class_status": None,
                "_horse_name": horse_name,
                "_rider_name": default_rider,
            })

    return entry_rows, horse_names, rider_names, time_ring_list


# -----------------------------------------------------------------------------
# Flow 1 – Step 7: Bulk upsert horses and riders; return name → id maps
# -----------------------------------------------------------------------------


async def upsert_horses_and_riders_and_get_maps(
    session: AsyncSession,
    farm_id: Any,
    horse_names: Set[str],
    rider_names: Set[str],
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    int,
    int,
    int,
    int,
]:
    """
    Bulk upsert horses and riders, then return name → UUID maps and counts.

    **Input (request):**
        - session: AsyncSession.
        - farm_id: Farm UUID.
        - horse_names: Set of horse names to ensure exist.
        - rider_names: Set of rider names to ensure exist.

    **Output (response):**
        - horse_name_to_id: Dict[horse_name, horse_uuid].
        - rider_name_to_id: Dict[rider_name, rider_uuid].
        - horses_inserted: Number of horse rows inserted.
        - horses_updated: Number of horse rows updated (0 when DO NOTHING).
        - riders_inserted: Number of rider rows inserted.
        - riders_updated: Number of rider rows updated (0 when DO NOTHING).

    **What it does:** bulk_upsert_horses / bulk_upsert_riders (ON CONFLICT DO NOTHING), then get_horse_ids_by_names / get_rider_ids_by_names to build the maps.
    """
    horses_inserted, horses_updated = await bulk_upsert_horses(
        session, farm_id, list(horse_names)
    )
    horse_id_list = await get_horse_ids_by_names(session, farm_id, list(horse_names))
    horse_name_to_id: Dict[str, Any] = {n: i for i, n in horse_id_list}
    riders_inserted, riders_updated = await bulk_upsert_riders(
        session, farm_id, list(rider_names)
    )
    rider_id_list = await get_rider_ids_by_names(session, farm_id, list(rider_names))
    rider_name_to_id: Dict[str, Any] = {n: i for i, n in rider_id_list}
    return (
        horse_name_to_id,
        rider_name_to_id,
        horses_inserted,
        horses_updated,
        riders_inserted,
        riders_updated,
    )


# -----------------------------------------------------------------------------
# Flow 1 – Step 8: Resolve entry rows (horse_id, rider_id) and bulk upsert entries
# -----------------------------------------------------------------------------


async def resolve_entry_rows_and_upsert(
    session: AsyncSession,
    entry_rows: List[Dict[str, Any]],
    horse_name_to_id: Dict[str, Any],
    rider_name_to_id: Dict[str, Any],
) -> Tuple[int, int, int]:
    """
    Replace _horse_name / _rider_name in entry rows with UUIDs, drop invalid rows, and bulk upsert entries.

    **Input (request):**
        - session: AsyncSession.
        - entry_rows: List of entry dicts with _horse_name and _rider_name (and all other DB columns).
        - horse_name_to_id: Map horse name → horse UUID.
        - rider_name_to_id: Map rider name → rider UUID.

    **Output (response):**
        - total_upserted: Number of entry rows actually upserted (after dropping rows with no horse_id).
        - entries_inserted: Number of entry rows newly inserted.
        - entries_updated: Number of entry rows updated.

    **What it does:** Pops _horse_name / _rider_name, sets horse_id and rider_id from maps; filters out rows with no horse_id; calls bulk_upsert_entries.
    """
    for row in entry_rows:
        row["horse_id"] = horse_name_to_id.get(row.pop("_horse_name", "") or "")
        _rn = row.pop("_rider_name", "") or ""
        row["rider_id"] = rider_name_to_id.get(_rn) if _rn else None
        if row["horse_id"] is None and horse_name_to_id:
            row["horse_id"] = next(iter(horse_name_to_id.values()))
    valid_rows = [r for r in entry_rows if r.get("horse_id") is not None]
    entries_inserted, entries_updated = 0, 0
    if valid_rows:
        entries_inserted, entries_updated = await bulk_upsert_entries(
            session, valid_rows
        )
    return len(valid_rows), entries_inserted, entries_updated


# -----------------------------------------------------------------------------
# Flow 1 – Step 9 (data only): Build summary for API response
# -----------------------------------------------------------------------------


def build_summary(
    sync_date_str: str,
    show_name: str,
    unique_horse_count: int,
    unique_class_count: int,
    total_synced_entries: int,
    time_ring_list: List[Tuple[str, str]],
    counts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the step-9 summary object (no Telegram send).

    **Input (request):**
        - sync_date_str: Sync date "YYYY-MM-DD" (day the sync was run).
        - show_name: Display name of the show.
        - unique_horse_count: Number of distinct horses.
        - unique_class_count: Number of distinct classes (rows in `classes` table).
        - total_synced_entries: Number of entry rows upserted (horse+class; rows in `entries` table).
        - time_ring_list: List of (estimated_start_utc_str, ring_name).
        - counts: Optional nested dict with show, rings, classes, horses, riders, entries (from_api/inserted/updated and entry stages). Included in summary when provided.

    **Output (response):**
        - summary: Dict with date, show_name, unique_horse_count, unique_class_count, total_synced_entries, unique_ring_count, first_class, last_class, and optionally "counts" (nested). first_class/last_class span the full show date range (may be outside sync date).

    **What it does:** Computes unique_ring_count from time_ring_list; sorts by time to set first_class and last_class; returns the summary dict for the API response.
    """
    unique_ring_count = len(set(rn for _, rn in time_ring_list))
    first_class: Optional[Dict[str, str]] = None
    last_class: Optional[Dict[str, str]] = None
    if time_ring_list:
        time_ring_list_sorted = sorted(time_ring_list, key=lambda x: x[0])
        first_class = {
            "time": time_ring_list_sorted[0][0],
            "ring_name": time_ring_list_sorted[0][1],
        }
        last_class = {
            "time": time_ring_list_sorted[-1][0],
            "ring_name": time_ring_list_sorted[-1][1],
        }
    out: Dict[str, Any] = {
        "date": sync_date_str,
        "show_name": show_name,
        "unique_horse_count": unique_horse_count,
        "unique_class_count": unique_class_count,
        "total_synced_entries": total_synced_entries,
        "total_class_entries": total_synced_entries,  # alias for backward compatibility (entry rows, not class count)
        "unique_ring_count": unique_ring_count,
        "first_class": first_class,
        "last_class": last_class,
    }
    if counts is not None:
        out["counts"] = counts
    return out


# -----------------------------------------------------------------------------
# Flow 1 – Orchestrator
# -----------------------------------------------------------------------------


async def run_daily_schedule(date_override: Optional[str] = None) -> dict[str, Any]:
    """
    Execute Flow 1 (Morning Sync) end-to-end: one DB session, optional date.

    **Input (request):**
        - date_override: Optional "YYYY-MM-DD". If None, uses today in UTC.

    **Output (response):**
        - Dict with keys: task ("completed"), trigger ("daily"), summary (date, show_name, unique_horse_count, unique_class_count, total_synced_entries, total_class_entries [alias], unique_ring_count, first_class, last_class). Does not send Telegram.

    **What it does:** Resolves sync date; opens one AsyncSession; ensures farm and token; fetches schedule and upserts show; upserts events and classes and builds id maps; fetches my entries and entry details in batches; builds entry rows and collects horses/riders; upserts horses and riders and resolves ids; resolves entry rows and bulk upserts entries; builds summary; commits and returns the response dict. On error, rolls back and re-raises.
    """
    sync_date_str, _sync_date = resolve_sync_date(date_override)
    customer_id_str = str(CUSTOMER_ID).strip() or "15"
    print("[Flow 1] Started | date=%s" % sync_date_str)

    async with AsyncSessionLocal() as session:
        try:
            farm_id, token = await ensure_farm_and_token(session)
            print("[Flow 1] Farm + token OK")
            logger.info("Farm resolved: id=%s", farm_id)

            (
                show_uuid,
                show_name,
                api_show_id,
                rings_data,
                _start_date,
                _end_date,
                show_inserted,
                show_updated,
            ) = await fetch_schedule_and_upsert_show(
                session, farm_id, sync_date_str, customer_id_str, token
            )
            print("[Flow 1] Schedule fetched | show=%s" % show_name)

            (
                ring_number_to_event_id,
                events_inserted,
                events_updated,
            ) = await upsert_events_and_build_ring_map(
                session, farm_id, rings_data
            )
            rings_from_api = len(rings_data)
            print("[Flow 1] Events (rings) upserted | from_api=%s inserted=%s updated=%s" % (rings_from_api, events_inserted, events_updated))

            (
                api_class_id_to_class_id,
                classes_from_api,
                classes_inserted,
                classes_updated,
            ) = await upsert_classes_and_build_class_map(
                session, farm_id, rings_data
            )
            print("[Flow 1] Classes upserted | from_api=%s inserted=%s updated=%s" % (classes_from_api, classes_inserted, classes_updated))

            entries_my = await get_entries_my(api_show_id, customer_id_str, token=token)
            entries_list = entries_my.get("entries") or []
            entries_from_api = len(entries_list)
            print("[Flow 1] My entries fetched | count=%s" % entries_from_api)

            entry_details = await fetch_entry_details(
                api_show_id, customer_id_str, token, entries_list
            )
            entry_details_fetched = len(entry_details)
            print("[Flow 1] Entry details fetched | count=%s" % entry_details_fetched)

            name_class_number_to_class_id = await get_or_create_class_map_from_entry_details(
                session, farm_id, entry_details
            )
            (
                entry_rows,
                horse_names,
                rider_names,
                time_ring_list,
            ) = build_entry_rows_and_collect_entities(
                entry_details,
                rings_data,
                show_uuid,
                ring_number_to_event_id,
                name_class_number_to_class_id,
                sync_date=_sync_date,
            )
            entry_rows_built = len(entry_rows)
            print("[Flow 1] Entry rows built | horses=%s riders=%s rows=%s" % (len(horse_names), len(rider_names), entry_rows_built))

            (
                horse_name_to_id,
                rider_name_to_id,
                horses_inserted,
                horses_updated,
                riders_inserted,
                riders_updated,
            ) = await upsert_horses_and_riders_and_get_maps(
                session, farm_id, horse_names, rider_names
            )
            horses_from_api = len(horse_names)
            riders_from_api = len(rider_names)
            print("[Flow 1] Horses + riders upserted | horses: from_api=%s inserted=%s updated=%s | riders: from_api=%s inserted=%s updated=%s" % (horses_from_api, horses_inserted, horses_updated, riders_from_api, riders_inserted, riders_updated))

            (
                total_synced_entries,
                entries_inserted,
                entries_updated,
            ) = await resolve_entry_rows_and_upsert(
                session, entry_rows, horse_name_to_id, rider_name_to_id
            )
            print("[Flow 1] Entries upserted | from_api=%s details_fetched=%s rows_built=%s inserted=%s updated=%s" % (entries_from_api, entry_details_fetched, entry_rows_built, entries_inserted, entries_updated))

            counts: Dict[str, Any] = {
                "show": {
                    "name": show_name,
                    "inserted": show_inserted,
                    "updated": show_updated,
                },
                "rings": _entity_counts(
                    from_api=rings_from_api,
                    inserted=events_inserted,
                    updated=events_updated,
                ),
                "classes": _entity_counts(
                    from_api=classes_from_api,
                    inserted=classes_inserted,
                    updated=classes_updated,
                ),
                "horses": _entity_counts(
                    from_api=horses_from_api,
                    inserted=horses_inserted,
                    updated=horses_updated,
                ),
                "riders": _entity_counts(
                    from_api=riders_from_api,
                    inserted=riders_inserted,
                    updated=riders_updated,
                ),
                "entries": _entry_counts(
                    from_api=entries_from_api,
                    entry_details_fetched=entry_details_fetched,
                    entry_rows_built=entry_rows_built,
                    inserted=entries_inserted,
                    updated=entries_updated,
                ),
            }
            summary = build_summary(
                sync_date_str,
                show_name,
                len(horse_names),
                len(name_class_number_to_class_id),  # distinct classes used for entries
                total_synced_entries,                # horse+class rows (rows in entries table)
                time_ring_list,
                counts=counts,
            )

            await session.commit()
            print("[Flow 1] Done | show=%s classes=%s entries=%s horses=%s" % (show_name, len(name_class_number_to_class_id), total_synced_entries, len(horse_names)))
            logger.info(
                "Flow 1 complete: show=%s classes=%s entries=%s horses=%s",
                show_name,
                len(name_class_number_to_class_id),
                total_synced_entries,
                len(horse_names),
            )
            return {
                "task": ScheduleTaskResult.COMPLETED.value,
                "trigger": ScheduleTriggerType.DAILY.value,
                "summary": summary,
            }
        except Exception as exc:
            await session.rollback()
            print("[Flow 1] Failed: %s" % exc)
            logger.exception("Daily scheduled task failed: %s", exc)
            raise
