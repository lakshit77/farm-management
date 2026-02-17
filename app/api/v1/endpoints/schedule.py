"""Schedule endpoints: daily job triggered by n8n (e.g. 7:00 AM) and schedule view for front-end."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.schemas.response import ApiResponse, success_response
from app.schemas.schedule_view import ScheduleViewData
from app.services.class_monitoring import run_class_monitoring
from app.services.schedule import resolve_sync_date, run_daily_schedule
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
    description="Called by n8n every 10 minutes. Runs Flow 2 (Class Monitoring): fetches active classes, detects changes, updates DB. Returns summary, structured changes, and pre-formatted alert messages (Telegram-style). Does not send Telegram; Step 7 (Flow 3 trigger) is a placeholder.",
)
async def class_monitor() -> ApiResponse[dict[str, Any]]:
    """
    Run Flow 2 (Class Monitoring). Returns data including changes and alerts for consumers.
    """
    data = await run_class_monitoring()
    return success_response(data=data)


@router.get(
    "/view",
    response_model=ApiResponse[ScheduleViewData],
    summary="Schedule view for date",
    description="Returns events (rings) with classes and entries (horse, rider, status) for the given date. For front-end display.",
)
async def schedule_view(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD. Default: today UTC."),
    session: AsyncSession = Depends(get_async_session),
) -> ApiResponse[ScheduleViewData]:
    """
    Load schedule for the given date: events → classes → entries with horse, rider, and backend status.
    """
    _, view_date = resolve_sync_date(date)
    data = await get_schedule_view(session, view_date)
    return success_response(data=data)
