"""
Service for persisting and querying notification log entries from class monitoring and future flows.

Callers pass an existing session so logs are written in the same transaction as other updates.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_log import (
    NotificationLog,
    get_recent_notifications as fetch_recent_notifications_from_db,
)

logger = logging.getLogger(__name__)


async def log_notification(
    session: AsyncSession,
    farm_id: UUID,
    source: str,
    notification_type: str,
    message: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    entry_id: Optional[UUID] = None,
) -> NotificationLog:
    """
    Insert one row into notification_log. Does not commit; caller must commit the session.

    **Input (request):**
        - session: AsyncSession (caller-owned; same transaction as entry updates).
        - farm_id: Farm UUID (tenant scope).
        - source: Origin of the notification (e.g. "class_monitoring", "horse_availability").
        - notification_type: Kind of event (STATUS_CHANGE, TIME_CHANGE, PROGRESS_UPDATE, etc.).
        - message: Optional human-readable alert message.
        - payload: Optional full structured change dict for querying.
        - entry_id: Optional entry UUID; show/class/horse resolvable via entry when needed.

    **Output (response):**
        - The created NotificationLog instance (already added to session).
    """
    row = NotificationLog(
        farm_id=farm_id,
        source=source,
        notification_type=notification_type,
        message=message,
        payload=payload,
        entry_id=entry_id,
    )
    session.add(row)
    await session.flush()  # so row.id is available if caller needs it
    return row


async def get_recent_notifications(
    session: AsyncSession,
    farm_id: UUID,
    limit: int = 50,
    offset: int = 0,
    source: Optional[str] = None,
    notification_type: Optional[str] = None,
    date_filter: Optional[date] = None,
    horse_name: Optional[str] = None,
    class_name: Optional[str] = None,
) -> List[NotificationLog]:
    """
    Return recent notification_log rows for a farm, optionally filtered by source, type, date,
    horse name, and class name.

    **Input (request):**
        - session: AsyncSession.
        - farm_id: Farm UUID to filter by.
        - limit: Max number of rows (default 50).
        - offset: Number of rows to skip (default 0), for pagination.
        - source: Optional filter (e.g. "class_monitoring").
        - notification_type: Optional filter (e.g. "STATUS_CHANGE").
        - date_filter: Optional single date; only rows with created_at on that day (00:00:00–23:59:59).
        - horse_name: Optional case-insensitive partial match on the associated entry's horse name.
        - class_name: Optional case-insensitive partial match on the associated entry's class name.

    **Output (response):**
        - List of NotificationLog instances ordered by created_at DESC.
    """
    rows = await fetch_recent_notifications_from_db(
        session,
        farm_id=farm_id,
        limit=limit,
        offset=offset,
        source=source,
        notification_type=notification_type,
        date_filter=date_filter,
        load_entry_relations=(horse_name is not None or class_name is not None),
    )
    # Post-filter by horse/class name through the entry relationship
    if horse_name is not None:
        hn_lower = horse_name.strip().lower()
        rows = [
            r for r in rows
            if r.entry and r.entry.horse and hn_lower in (r.entry.horse.name or "").lower()
        ]
    if class_name is not None:
        cn_lower = class_name.strip().lower()
        rows = [
            r for r in rows
            if r.entry and r.entry.show_class and cn_lower in (r.entry.show_class.name or "").lower()
        ]
    return rows
