"""Schedule endpoints: daily job triggered by n8n (e.g. 7:00 AM) and schedule view for front-end."""

from datetime import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.schemas.notification_log import NotificationLogItem, NotificationLogListData
from app.schemas.response import ApiResponse, success_response
from app.schemas.schedule_view import ScheduleViewData
from app.services.class_monitoring import run_class_monitoring
from app.services.notification_log import get_recent_notifications
from app.services.schedule import ensure_farm_and_token, resolve_sync_date, run_daily_schedule
from app.services.schedule_view import get_schedule_view

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get(
    "/daily",
    response_model=ApiResponse[dict[str, Any]],
    summary="Daily schedule trigger",
    description="Called by n8n daily (e.g. 7:00 AM). Runs Flow 1 (Morning Sync). Optional date in UTC (YYYY-MM-DD).",
)
async def daily_schedule(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD (UTC). Default: today UTC."),
) -> ApiResponse[dict[str, Any]]:
    """
    Handle the request, call the daily schedule logic, and return the API response with summary.
    """
    data = await run_daily_schedule(date_override=date)
    return success_response(data=data)


@router.get(
    "/class-monitor",
    response_model=ApiResponse[dict[str, Any]],
    summary="Class monitoring trigger (Flow 2)",
    description="Called by n8n every 10 minutes. Runs Flow 2 (Class Monitoring): fetches active classes, detects changes, updates DB. Returns summary, structured changes, and pre-formatted alert messages (Telegram-style). Optional date in UTC (YYYY-MM-DD). Does not send Telegram; Step 7 (Flow 3 trigger) is a placeholder.",
)
async def class_monitor(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD (UTC). Default: today UTC."),
) -> ApiResponse[dict[str, Any]]:
    """
    Run Flow 2 (Class Monitoring). Returns data including changes and alerts for consumers.
    Last run time is stored on the farm (farms.class_monitoring_last_run_at).
    """
    data = await run_class_monitoring(date_override=date)
    return success_response(data=data)


@router.get(
    "/view",
    response_model=ApiResponse[ScheduleViewData],
    summary="Schedule view for date",
    description="Returns events (rings) with classes and entries (horse, rider, status) for the given date. For front-end display. Optional horse_name and class_name filters narrow results server-side.",
)
async def schedule_view(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD. Default: today UTC."),
    horse_name: Optional[str] = Query(None, description="Filter entries by horse name (case-insensitive partial match)."),
    class_name: Optional[str] = Query(None, description="Filter classes by class name (case-insensitive partial match)."),
    session: AsyncSession = Depends(get_async_session),
) -> ApiResponse[ScheduleViewData]:
    """
    Load schedule for the given date: events → classes → entries with horse, rider, and backend status.
    Optional horse_name and class_name narrow results to matching entries/classes only.
    """
    _, view_date = resolve_sync_date(date)
    data = await get_schedule_view(session, view_date, horse_name=horse_name, class_name=class_name)
    return success_response(data=data)


@router.get(
    "/notifications",
    response_model=ApiResponse[NotificationLogListData],
    summary="Recent notification log",
    description="Returns recent notification log entries for the current farm. Optional: date, source, notification_type, horse_name, class_name, limit, offset.",
)
async def list_notifications(
    limit: int = Query(50, ge=1, le=500, description="Max number of notifications to return."),
    offset: int = Query(0, ge=0, description="Number of notifications to skip (for load more)."),
    source: Optional[str] = Query(None, description="Filter by source (e.g. class_monitoring)."),
    notification_type: Optional[str] = Query(None, description="Filter by type (e.g. STATUS_CHANGE)."),
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD); only notifications from that day."),
    horse_name: Optional[str] = Query(None, description="Filter by horse name (case-insensitive partial match via entry relationship)."),
    class_name: Optional[str] = Query(None, description="Filter by class name (case-insensitive partial match via entry relationship)."),
    session: AsyncSession = Depends(get_async_session),
) -> ApiResponse[NotificationLogListData]:
    """
    List recent notifications for the current farm. Farm is resolved via ensure_farm_and_token.
    Optional horse_name and class_name filter by matching the associated entry's horse/class name.
    """
    farm_id, _ = await ensure_farm_and_token(session)
    date_filter = None
    if date:
        try:
            date_filter = dt.strptime(date, "%Y-%m-%d").date()  # noqa: DTZ007
        except ValueError:
            pass
    rows = await get_recent_notifications(
        session,
        farm_id=farm_id,
        limit=limit,
        offset=offset,
        source=source,
        notification_type=notification_type,
        date_filter=date_filter,
        horse_name=horse_name,
        class_name=class_name,
    )
    data = NotificationLogListData(
        notifications=[NotificationLogItem.model_validate(r) for r in rows],
    )
    return success_response(data=data)
