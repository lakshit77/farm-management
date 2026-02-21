"""
Flow 3: Horse Availability Tracker — calculate horse's free time and next scheduled class
after completing a class. Logs availability message to notification_log (no Telegram).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import NotificationSource, NotificationType
from app.models.entry import Entry, get_horse_remaining_entries_today
from app.services.notification_log import log_notification

logger = logging.getLogger(__name__)


def _parse_estimated_start_naive(
    estimated_start: Optional[str], scheduled_date: Optional[date]
) -> Optional[datetime]:
    """
    Parse estimated_start to naive datetime (no timezone).

    estimated_start is stored as "YYYY-MM-DD HH:MM:SS" or "HH:MM:SS".
    Returns naive datetime; caller must localize to venue timezone.
    """
    if not estimated_start:
        return None
    s = str(estimated_start).strip()
    if not s:
        return None
    # Try "YYYY-MM-DD HH:MM:SS" first (primary format from schedule sync)
    try:
        if " " in s and len(s) >= 19:
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        pass
    # Try time-only "HH:MM:SS" with scheduled_date
    try:
        if scheduled_date and ":" in s:
            parts = s.split(":")
            if len(parts) >= 2:
                h, m = int(parts[0]), int(parts[1])
                sec = int(parts[2]) if len(parts) >= 3 else 0
                return datetime.combine(scheduled_date, time(h, m, sec))
    except (ValueError, TypeError):
        pass
    # Fallback: fromisoformat (may include Z)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, TypeError):
        return None
    return None


def _parse_estimated_start(estimated_start: Optional[str], scheduled_date: Optional[date]) -> Optional[datetime]:
    """
    Parse estimated_start to UTC datetime for free-time calculation.

    API/schedule stores times in venue local (e.g. Eastern for Wellington FL).
    We localize to VENUE_TIMEZONE then convert to UTC for comparison with now(UTC).
    """
    naive = _parse_estimated_start_naive(estimated_start, scheduled_date)
    if naive is None:
        return None
    try:
        tz = ZoneInfo(get_settings().VENUE_TIMEZONE)
        return naive.replace(tzinfo=tz).astimezone(timezone.utc)
    except Exception as e:
        logger.warning(
            "Flow 3: could not localize estimated_start=%s to venue tz: %s; falling back to naive as UTC",
            estimated_start,
            e,
        )
        return naive.replace(tzinfo=timezone.utc)


def _format_time_display(estimated_start: Optional[str], scheduled_date: Optional[date]) -> str:
    """Format estimated_start for display in message (e.g. '11:50'). Uses naive parse to preserve local time."""
    dt = _parse_estimated_start_naive(estimated_start, scheduled_date)
    if dt is None:
        return estimated_start or "—"
    return dt.strftime("%H:%M") if scheduled_date else dt.strftime("%Y-%m-%d %H:%M")


async def get_remaining_classes_today(
    session: AsyncSession,
    horse_id: UUID,
    show_id: UUID,
    completed_entry_id: UUID,
    today: date,
) -> List[Entry]:
    """
    Get horse's remaining classes today (incomplete, not gone, excluding completed entry).

    **Input (request):**
        - session: AsyncSession.
        - horse_id: Horse UUID.
        - show_id: Show UUID.
        - completed_entry_id: Entry UUID just completed (excluded from results).
        - today: Date to filter (scheduled_date).

    **Output (response):**
        - List of Entry instances ordered by estimated_start ASC, with show_class and event loaded.
    """
    return await get_horse_remaining_entries_today(
        session, horse_id, show_id, completed_entry_id, today
    )


def _build_availability_message(
    horse_name: str,
    completed_class_name: str,
    completed_ring_name: str,
    has_next: bool,
    next_class_name: Optional[str] = None,
    next_class_time: Optional[str] = None,
    next_ring_name: Optional[str] = None,
    order_of_go: Optional[int] = None,
    order_total: Optional[int] = None,
    free_hours: Optional[int] = None,
    free_mins: Optional[int] = None,
) -> str:
    """
    Build the availability message (same format as Telegram template in FLOWS.md).

    Stored in notification_log.message instead of being sent via Telegram.
    """
    if has_next and next_class_name:
        order_str = (
            f"#{order_of_go} of {order_total}"
            if order_of_go is not None and order_total is not None
            else ""
        )
        free_str = (
            f"{free_hours}h {free_mins}m"
            if free_hours is not None and free_mins is not None
            else "—"
        )
        return (
            f"🐴 {horse_name} - Trip Completed\n\n"
            f"✅ Finished: {completed_class_name}\n"
            f"📍 Ring: {completed_ring_name}\n\n"
            f"⏭️ Next: {next_class_name}\n"
            f"⏰ Time: {next_class_time or '—'}\n"
            f"📍 Ring: {next_ring_name or '—'}\n"
            + (f"#️⃣ Order: {order_str}\n\n" if order_str else "\n")
            + f"⏳ Free time: {free_str}"
        )
    return (
        f"🐴 {horse_name} - Done for Today!\n\n"
        f"✅ Finished: {completed_class_name}\n"
        f"📍 Ring: {completed_ring_name}\n\n"
        "🎉 No more classes scheduled today"
    )


async def run_flow_3_horse_availability(
    session: AsyncSession,
    farm_id: UUID,
    horse_id: UUID,
    horse_name: str,
    completed_entry_id: UUID,
    completed_class_id: UUID,
    show_id: UUID,
    completed_class_name: str,
    completed_ring_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Execute Flow 3: calculate free time, build message, log to notification_log.

    Does not send Telegram; the message is stored in notification_log.

    **Input (request):**
        - session: AsyncSession (caller-owned; same transaction as Flow 2 updates).
        - farm_id: Farm UUID (for notification_log).
        - horse_id: Horse UUID.
        - horse_name: Horse display name.
        - completed_entry_id: Entry UUID just completed.
        - completed_class_id: Class UUID just completed.
        - show_id: Show UUID.
        - completed_class_name: Class name for message.
        - completed_ring_name: Ring name for message.

    **Output (response):**
        - Dict with keys: has_next, free_hours, free_mins, next_class_name, etc. (for logging/debug).
        - None if an error occurs.
    """
    today = datetime.now(timezone.utc).date()
    try:
        remaining = await get_remaining_classes_today(
            session,
            horse_id=horse_id,
            show_id=show_id,
            completed_entry_id=completed_entry_id,
            today=today,
        )
    except Exception as e:
        logger.exception(
            "Flow 3: get_remaining_classes_today failed for horse_id=%s: %s",
            horse_id,
            e,
        )
        return None

    current_time = datetime.now(timezone.utc)
    has_next = len(remaining) > 0
    free_hours: Optional[int] = None
    free_mins: Optional[int] = None
    next_class_name: Optional[str] = None
    next_class_time: Optional[str] = None
    next_ring_name: Optional[str] = None
    order_of_go: Optional[int] = None
    order_total: Optional[int] = None

    if has_next:
        next_entry = remaining[0]
        next_class_name = (
            next_entry.show_class.name if next_entry.show_class else "Unknown Class"
        )
        next_ring_name = (
            next_entry.event.name if next_entry.event else "Unknown Ring"
        )
        next_class_time = _format_time_display(
            next_entry.estimated_start, next_entry.scheduled_date
        )
        order_of_go = next_entry.order_of_go
        order_total = next_entry.order_total

        next_dt = _parse_estimated_start(
            next_entry.estimated_start, next_entry.scheduled_date
        )
        if next_dt is not None:
            free_delta = next_dt - current_time
            free_seconds = free_delta.total_seconds()
            if free_seconds > 0:
                free_minutes = free_seconds / 60
                free_hours = int(free_minutes // 60)
                free_mins = int(free_minutes % 60)
            else:
                free_hours = 0
                free_mins = 0

    message = _build_availability_message(
        horse_name=horse_name,
        completed_class_name=completed_class_name,
        completed_ring_name=completed_ring_name,
        has_next=has_next,
        next_class_name=next_class_name,
        next_class_time=next_class_time,
        next_ring_name=next_ring_name,
        order_of_go=order_of_go,
        order_total=order_total,
        free_hours=free_hours,
        free_mins=free_mins,
    )

    payload: Dict[str, Any] = {
        "horse_id": str(horse_id),
        "horse_name": horse_name,
        "completed_class_id": str(completed_class_id),
        "completed_entry_id": str(completed_entry_id),
        "show_id": str(show_id),
        "has_next": has_next,
        "free_hours": free_hours,
        "free_mins": free_mins,
    }
    if has_next:
        payload["next_class_name"] = next_class_name
        payload["next_class_time"] = next_class_time
        payload["next_ring_name"] = next_ring_name
        payload["order_of_go"] = order_of_go
        payload["order_total"] = order_total

    try:
        await log_notification(
            session,
            farm_id=farm_id,
            source=NotificationSource.HORSE_AVAILABILITY.value,
            notification_type=NotificationType.HORSE_COMPLETED.value,
            message=message,
            payload=payload,
            entry_id=completed_entry_id,
        )
    except Exception as e:
        logger.exception(
            "Flow 3: log_notification failed for horse_id=%s: %s",
            horse_id,
            e,
        )
        return None

    logger.debug(
        "Flow 3: logged availability for horse_id=%s has_next=%s",
        horse_id,
        has_next,
    )
    return payload
