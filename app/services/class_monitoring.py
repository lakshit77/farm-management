"""
Flow 2: Class Monitoring — monitor active classes for changes and return alert info in response.

Steps 1–5 implemented; Step 6 (Telegram) not sent — structured changes and formatted alert
messages are returned in the API response; Step 7 (Trigger Flow 3) is a no-op placeholder.

Concurrency: all get_class API calls run in parallel via asyncio.gather; change detection
and DB updates run sequentially in a single session to avoid session races and row conflicts.
"""

import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import CUSTOMER_ID
from app.core.database import AsyncSessionLocal
from app.models.entry import Entry
from app.models.show import Show
from app.services.notification_log import log_notification
from app.services.schedule import ensure_farm_and_token
from app.services.wellington_client import WellingtonAPIError, get_class

logger = logging.getLogger(__name__)

# Placeholder: 100000 = unplaced (per API docs)
UNPLACED_PLACING = 100000


# -----------------------------------------------------------------------------
# Step 7 (placeholder): Trigger Flow 3 when horse completes — to be implemented later
# -----------------------------------------------------------------------------


async def trigger_flow_3_if_needed(
    horse_id: str,
    horse_name: str,
    completed_class_id: str,
    show_id: str,
) -> None:
    """
    Placeholder for Flow 3 (Horse Availability). Called when a horse completes a trip (gone_in 0→1).

    To be implemented later: will trigger Flow 3 with the given parameters to calculate
    horse's free time and next scheduled class.

    **Input (request):**
        - horse_id: Horse UUID.
        - horse_name: Horse display name.
        - completed_class_id: Class UUID just completed.
        - show_id: Current show UUID.
    """
    # TODO: Implement Flow 3 trigger (e.g. call Flow 3 service or enqueue job).
    logger.debug(
        "Flow 3 placeholder: would trigger for horse_id=%s horse_name=%s completed_class_id=%s show_id=%s",
        horse_id,
        horse_name,
        completed_class_id,
        show_id,
    )
    pass


# -----------------------------------------------------------------------------
# Step 1: Get active entries for today (incomplete classes)
# -----------------------------------------------------------------------------


async def get_active_classes_and_entries(
    session: AsyncSession,
    farm_id: Any,
    today: date,
) -> List[Tuple[Any, int, List[Any]]]:
    """
    Return list of (show_id_uuid, api_show_id, entries_for_class) for each distinct
    active class today. Each entry has horse, show_class, event, show loaded.

    **Input (request):**
        - session: AsyncSession.
        - farm_id: Farm UUID.
        - today: Date to filter (scheduled_date).

    **Output (response):**
        - List of (show_id UUID, api_show_id int, list of Entry ORM objects with relations).
    """
    stmt = (
        select(Entry)
        .join(Show, Entry.show_id == Show.id)
        .where(
            and_(
                Show.farm_id == farm_id,
                Entry.scheduled_date == today,
                Entry.api_class_id.isnot(None),
                (Entry.class_status.is_(None) | (Entry.class_status != "Completed")),
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
    all_entries = list(result.scalars().unique())

    # Group by (api_class_id, show_id) — same class in same show
    by_class: Dict[Tuple[int, Any], List[Any]] = {}
    for e in all_entries:
        if e.api_class_id is None or e.show_id is None or e.show is None:
            continue
        key = (e.api_class_id, e.show_id)
        by_class.setdefault(key, []).append(e)

    out: List[Tuple[Any, int, List[Any]]] = []
    seen: set = set()
    for (api_class_id, show_id_uuid), entries in by_class.items():
        api_show_id = entries[0].show.api_show_id if entries[0].show else None
        if api_show_id is None:
            continue
        # Dedupe by (api_class_id, api_show_id)
        if (api_class_id, api_show_id) in seen:
            continue
        seen.add((api_class_id, api_show_id))
        out.append((show_id_uuid, api_show_id, entries))
    return out


# -----------------------------------------------------------------------------
# Helpers: parse time (API returns "07:15:00"), format alert messages
# -----------------------------------------------------------------------------


def _parse_time(s: Optional[str]) -> Optional[str]:
    """Normalize API time string for comparison (e.g. '07:15:00' -> keep as-is)."""
    if s is None or not isinstance(s, str):
        return None
    return s.strip() or None


def _normalize_time_for_comparison(s: Optional[str]) -> Optional[str]:
    """
    Return time-only part (HH:MM:SS) for comparison.
    DB may store 'YYYY-MM-DD HH:MM:SS'; API returns 'HH:MM:SS'. Normalizing avoids false TIME_CHANGE.
    """
    if s is None or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    if " " in s:
        s = s.split()[-1]
    return s if s else None


def _format_alert_status_change(
    change: Dict[str, Any],
    our_entries: List[Any],
    trips: List[Dict],
    ring_name: str,
) -> str:
    """Build STATUS_CHANGE alert message (Class Started or Class Completed)."""
    class_name = change.get("class_name") or "Unknown Class"
    new_status = change.get("new") or ""

    if new_status == "Completed":
        # Our Results: horse — Place #n, $prize
        lines = ["🏁 Class Completed", "", f"📋 {class_name}", f"📍 {ring_name}", "", "Our Results:"]
        entry_id_to_trip = {t.get("entry_id"): t for t in trips if t.get("entry_id")}
        for e in our_entries:
            api_eid = e.api_entry_id
            trip = entry_id_to_trip.get(api_eid) if api_eid else None
            horse_name = (e.horse.name if e.horse else None) or "Unknown"
            if trip is not None:
                placing = trip.get("placing")
                prize = trip.get("total_prize_money")
                if placing is not None and placing > 0 and placing < UNPLACED_PLACING:
                    lines.append(f"  {horse_name} — Place #{placing}, ${prize or 0}")
                else:
                    lines.append(f"  {horse_name} — No placing")
            else:
                lines.append(f"  {horse_name}")
        return "\n".join(lines)

    # Class Started: only for Underway / In Progress (not for "Not Started")
    if new_status in ("Underway", "In Progress"):
        horse_list = []
        order_list = []
        entry_id_to_trip = {t.get("entry_id"): t for t in trips if t.get("entry_id")}
        for e in our_entries:
            horse_name = (e.horse.name if e.horse else None) or "Unknown"
            horse_list.append(horse_name)
            trip = entry_id_to_trip.get(e.api_entry_id) if e.api_entry_id else None
            order_list.append(
                str(trip.get("order_of_go")) if (trip and trip.get("order_of_go") is not None) else "unk"
            )
        return (
            "🟢 Class Started\n\n"
            f"📋 {class_name}\n"
            f"📍 {ring_name}\n"
            f"🐴 Our horses: {', '.join(horse_list)}\n"
            f"#️⃣ Order: {', '.join(order_list)}"
        )

    # Fallback for any other status (e.g. unknown API value)
    return f"Status: {new_status}\n\n📋 {class_name}\n📍 {ring_name}"


def _format_alert_time_change(change: Dict[str, Any], ring_name: str) -> str:
    """Build TIME_CHANGE alert message."""
    class_name = change.get("class_name") or "Unknown Class"
    old_t = change.get("old") or "—"
    new_t = change.get("new") or "—"
    return (
        "⏰ Time Change\n\n"
        f"📋 {class_name}\n"
        f"📍 {ring_name}\n"
        f"🕐 {old_t} → {new_t}"
    )


def _format_alert_result(change: Dict[str, Any]) -> str:
    """Build RESULT alert message."""
    horse = change.get("horse") or "Unknown"
    class_name = change.get("class_name") or "Unknown Class"
    placing = change.get("placing") or 0
    prize = change.get("prize_money") or 0
    return (
        "🏆 Result!\n\n"
        f"🐴 {horse}\n"
        f"📋 {class_name}\n"
        f"🥇 Place: #{placing}\n"
        f"💰 Prize: ${prize}"
    )


def _format_alert_horse_completed(change: Dict[str, Any], faults: Any = None, time_s: Any = None) -> str:
    """Build HORSE_COMPLETED alert message. faults and time_s can come from trip if needed."""
    horse = change.get("horse") or "Unknown"
    class_name = change.get("class_name") or "Unknown Class"
    f_val = faults if faults is not None else "—"
    t_val = time_s if time_s is not None else "—"
    return (
        "✅ Trip Completed\n\n"
        f"🐴 {horse}\n"
        f"📋 {class_name}\n"
        f"📊 Faults: {f_val} | Time: {t_val}s"
    )


def _format_alert_scratched(change: Dict[str, Any]) -> str:
    """Build SCRATCHED alert message."""
    horse = change.get("horse") or "Unknown"
    class_name = change.get("class_name") or "Unknown Class"
    return (
        "❌ Horse Scratched\n\n"
        f"🐴 {horse}\n"
        f"📋 {class_name}"
    )


def _format_alert_progress(change: Dict[str, Any], ring_name: str) -> str:
    """Build PROGRESS_UPDATE message (optional; not in FLOWS templates but useful)."""
    class_name = change.get("class_name") or "Unknown Class"
    completed = change.get("completed", 0)
    total = change.get("total", 0)
    return (
        "📊 Progress Update\n\n"
        f"📋 {class_name}\n"
        f"📍 {ring_name}\n"
        f"Completed: {completed}/{total}"
    )


# -----------------------------------------------------------------------------
# Steps 2–5 + change detection + alert message building (per class)
# -----------------------------------------------------------------------------


def _trip_for_entry(trips: List[Dict], api_entry_id: Optional[int]) -> Optional[Dict]:
    """Find trip matching api_entry_id."""
    if api_entry_id is None:
        return None
    for t in trips:
        if t.get("entry_id") == api_entry_id:
            return t
    return None


def _entry_status(scratch_trip: bool, gone_in: bool) -> str:
    """Derived status: scratched > completed > active."""
    if scratch_trip:
        return "scratched"
    if gone_in:
        return "completed"
    return "active"


def _safe_decimal(v: Any) -> Optional[Decimal]:
    """Convert API value to Decimal for DB."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _safe_int(v: Any) -> Optional[int]:
    """Convert API value to int for DB."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except Exception:
        return None


def _safe_str(v: Any, max_len: int = 50) -> Optional[str]:
    """Convert API value to string for DB."""
    if v is None:
        return None
    s = str(v).strip()
    return s[:max_len] if s else None


async def _fetch_class_data(
    api_class_id: int,
    api_show_id: int,
    customer_id_str: str,
    token: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetch class data from the API (I/O only, no DB). Used for parallel fetching.

    Returns class payload dict on success, None on API error. Exceptions are caught and logged.
    """
    try:
        return await get_class(api_class_id, api_show_id, customer_id_str, token=token)
    except WellingtonAPIError as e:
        logger.warning("Flow 2: get_class failed for api_class_id=%s: %s", api_class_id, e)
        return None


async def _process_one_class_with_data(
    session: AsyncSession,
    show_id_uuid: Any,
    api_show_id: int,
    entries: List[Any],
    class_data: Optional[Dict[str, Any]],
) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, str]]]:
    """
    Match trips, detect changes, update DB, build changes + alerts. No I/O; uses pre-fetched class_data.

    Call only from a single task so the session is not used concurrently (avoids race conditions).
    Returns (entries_updated_count, changes, alerts). If class_data is None, returns (0, [], []).
    """
    if not entries or class_data is None:
        return 0, [], []

    first = entries[0]
    farm_id = first.show.farm_id if first.show else None
    class_name = (first.show_class.name if first.show_class else None) or "Unknown Class"
    ring_name = (first.event.name if first.event else None) or "Unknown Ring"
    crd = class_data.get("class_related_data") or {}
    trips = class_data.get("trips") or []
    api_status = _safe_str(crd.get("status"))
    api_estimated = _parse_time(crd.get("estimated_time"))
    api_actual = _parse_time(crd.get("actual_time"))
    api_total_trips = _safe_int(crd.get("total_trips"))
    api_completed_trips = _safe_int(crd.get("completed_trips"))
    api_remaining_trips = _safe_int(crd.get("remaining_trips"))

    changes: List[Dict[str, Any]] = []
    alerts: List[Dict[str, str]] = []  # [{ "type": "...", "message": "..." }]

    # ---------- Class-level changes ----------
    if api_status != first.class_status:
        # Don't emit STATUS_CHANGE when new status is "Not Started" (incl. null -> "Not Started")
        if api_status == "Not Started":
            pass
        else:
            ch = {
                "type": "STATUS_CHANGE",
                "old": first.class_status,
                "new": api_status,
                "class_name": class_name,
            }
            changes.append(ch)
            msg = _format_alert_status_change(ch, entries, trips, ring_name)
            alerts.append({"type": "STATUS_CHANGE", "message": msg})
            if farm_id is not None:
                await log_notification(
                    session,
                    farm_id=farm_id,
                    source="class_monitoring",
                    notification_type="STATUS_CHANGE",
                    message=msg,
                    payload=ch,
                    entry_id=first.id,
                )

    norm_old_time = _normalize_time_for_comparison(first.estimated_start)
    norm_new_time = _normalize_time_for_comparison(api_estimated)
    if api_estimated is not None and norm_old_time != norm_new_time:
        ch = {
            "type": "TIME_CHANGE",
            "old": first.estimated_start or "—",
            "new": api_estimated,
            "class_name": class_name,
        }
        changes.append(ch)
        time_msg = _format_alert_time_change(ch, ring_name)
        alerts.append({
            "type": "TIME_CHANGE",
            "message": time_msg,
        })
        if farm_id is not None:
            await log_notification(
                session,
                farm_id=farm_id,
                source="class_monitoring",
                notification_type="TIME_CHANGE",
                message=time_msg,
                payload=ch,
                entry_id=first.id,
            )

    if api_completed_trips is not None and api_completed_trips != first.completed_trips:
        ch = {
            "type": "PROGRESS_UPDATE",
            "completed": api_completed_trips,
            "total": api_total_trips or 0,
            "class_name": class_name,
        }
        changes.append(ch)
        progress_msg = _format_alert_progress(ch, ring_name)
        alerts.append({
            "type": "PROGRESS_UPDATE",
            "message": progress_msg,
        })
        if farm_id is not None:
            await log_notification(
                session,
                farm_id=farm_id,
                source="class_monitoring",
                notification_type="PROGRESS_UPDATE",
                message=progress_msg,
                payload=ch,
                entry_id=first.id,
            )

    # ---------- Entry-level: match trips and detect changes ----------
    updated = 0
    for entry in entries:
        trip = _trip_for_entry(trips, entry.api_entry_id)
        if trip is None:
            continue

        gone_in = (trip.get("gone_in") == 1)
        scratch_trip = (trip.get("scratch_trip") == 1)
        placing = _safe_int(trip.get("placing"))
        prize = trip.get("total_prize_money")
        horse_name = (entry.horse.name if entry.horse else None) or "Unknown"

        # Result posted
        if placing is not None and entry.placing != placing and 0 < placing < UNPLACED_PLACING:
            ch = {
                "type": "RESULT",
                "horse": horse_name,
                "placing": placing,
                "prize_money": prize,
                "class_name": class_name,
            }
            changes.append(ch)
            result_msg = _format_alert_result(ch)
            alerts.append({"type": "RESULT", "message": result_msg})
            if farm_id is not None:
                await log_notification(
                    session,
                    farm_id=farm_id,
                    source="class_monitoring",
                    notification_type="RESULT",
                    message=result_msg,
                    payload=ch,
                    entry_id=entry.id,
                )

        # Horse completed trip
        if gone_in and not entry.gone_in:
            ch = {
                "type": "HORSE_COMPLETED",
                "horse": horse_name,
                "horse_id": str(entry.horse_id),
                "class_name": class_name,
            }
            changes.append(ch)
            faults = trip.get("faults_one")
            time_one = trip.get("time_one")
            horse_completed_msg = _format_alert_horse_completed(ch, faults=faults, time_s=time_one)
            alerts.append({
                "type": "HORSE_COMPLETED",
                "message": horse_completed_msg,
            })
            if farm_id is not None:
                await log_notification(
                    session,
                    farm_id=farm_id,
                    source="class_monitoring",
                    notification_type="HORSE_COMPLETED",
                    message=horse_completed_msg,
                    payload=ch,
                    entry_id=entry.id,
                )
            # Step 7 placeholder: trigger Flow 3 when horse completes
            await trigger_flow_3_if_needed(
                str(entry.horse_id),
                horse_name,
                str(entry.class_id) if entry.class_id else "",
                str(entry.show_id) if entry.show_id else "",
            )

        # Horse scratched
        if scratch_trip and not entry.scratch_trip:
            ch = {
                "type": "SCRATCHED",
                "horse": horse_name,
                "class_name": class_name,
            }
            changes.append(ch)
            scratched_msg = _format_alert_scratched(ch)
            alerts.append({"type": "SCRATCHED", "message": scratched_msg})
            if farm_id is not None:
                await log_notification(
                    session,
                    farm_id=farm_id,
                    source="class_monitoring",
                    notification_type="SCRATCHED",
                    message=scratched_msg,
                    payload=ch,
                    entry_id=entry.id,
                )

        # ---------- Update entry (Step 5) ----------
        entry.class_status = api_status
        entry.estimated_start = api_estimated
        entry.actual_start = api_actual
        entry.total_trips = api_total_trips
        entry.completed_trips = api_completed_trips
        entry.remaining_trips = api_remaining_trips
        entry.api_trip_id = _safe_int(trip.get("trip_id"))
        entry.order_of_go = _safe_int(trip.get("order_of_go"))
        entry.placing = placing
        entry.faults_one = _safe_decimal(trip.get("faults_one"))
        entry.time_one = _safe_decimal(trip.get("time_one"))
        entry.time_fault_one = _safe_decimal(trip.get("time_fault_one"))
        entry.faults_two = _safe_decimal(trip.get("faults_two"))
        entry.time_two = _safe_decimal(trip.get("time_two"))
        entry.time_fault_two = _safe_decimal(trip.get("time_fault_two"))
        entry.total_prize_money = _safe_decimal(prize)
        entry.points_earned = _safe_decimal(trip.get("points_earned"))
        entry.gone_in = gone_in
        entry.scratch_trip = scratch_trip
        entry.disqualify_status_one = _safe_str(trip.get("disqualify_status_one"))
        entry.disqualify_status_two = _safe_str(trip.get("disqualify_status_two"))
        entry.score1 = _safe_decimal(trip.get("score1"))
        entry.score2 = _safe_decimal(trip.get("score2"))
        entry.score3 = _safe_decimal(trip.get("score3"))
        entry.score4 = _safe_decimal(trip.get("score4"))
        entry.score5 = _safe_decimal(trip.get("score5"))
        entry.score6 = _safe_decimal(trip.get("score6"))
        entry.status = _entry_status(scratch_trip, gone_in)
        entry.updated_at = datetime.now(timezone.utc)
        session.add(entry)
        updated += 1

    return updated, changes, alerts


# -----------------------------------------------------------------------------
# Flow 2 orchestrator
# -----------------------------------------------------------------------------


async def run_class_monitoring() -> Dict[str, Any]:
    """
    Execute Flow 2 (Class Monitoring) end-to-end: one DB session, same farm/customer as Flow 1.

    **Output (response):**
        - summary: classes_checked, entries_updated, total_changes, total_alerts.
        - changes: list of structured change objects (type, class_name, horse, etc.).
        - alerts: list of { "type", "message" } with pre-formatted alert text (Telegram-style).
        Step 6 (Telegram) is not implemented — alert info is in the response.
        Step 7 (Trigger Flow 3) is a no-op placeholder.
    """
    today = datetime.now(timezone.utc).date()
    customer_id_str = (CUSTOMER_ID or "").strip() or "15"

    async with AsyncSessionLocal() as session:
        try:
            farm_id, token = await ensure_farm_and_token(session)
            classes_and_entries = await get_active_classes_and_entries(session, farm_id, today)
        except Exception as e:
            logger.exception("Flow 2: ensure_farm or get_active_classes failed: %s", e)
            raise

        # Fetch all class data in parallel (I/O only); no shared session, no DB writes
        fetch_tasks = [
            _fetch_class_data(entries[0].api_class_id, api_show_id, customer_id_str, token)
            for _, api_show_id, entries in classes_and_entries
        ]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Resolve exceptions to None so processing can skip failed fetches
        class_data_list: List[Optional[Dict[str, Any]]] = []
        for i, result in enumerate(fetch_results):
            if isinstance(result, Exception):
                logger.warning(
                    "Flow 2: get_class failed for class index %s: %s",
                    i,
                    result,
                    exc_info=True,
                )
                class_data_list.append(None)
            else:
                class_data_list.append(result)

        # Process and update DB sequentially with one session to avoid race conditions
        all_changes: List[Dict[str, Any]] = []
        all_alerts: List[Dict[str, str]] = []
        total_updated = 0
        for (show_id_uuid, api_show_id, entries), class_data in zip(
            classes_and_entries,
            class_data_list,
        ):
            updated, changes, alerts = await _process_one_class_with_data(
                session,
                show_id_uuid,
                api_show_id,
                entries,
                class_data,
            )
            total_updated += updated
            all_changes.extend(changes)
            all_alerts.extend(alerts)

        await session.commit()

    return {
        "summary": {
            "date": today.isoformat(),
            "classes_checked": len(classes_and_entries),
            "entries_updated": total_updated,
            "total_changes": len(all_changes),
            "total_alerts": len(all_alerts),
        },
        "changes": all_changes,
        "alerts": all_alerts,
    }
