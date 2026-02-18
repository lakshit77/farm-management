"""
Service for persisting and querying notification log entries from class monitoring and future flows.

Callers pass an existing session so logs are written in the same transaction as other updates.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_log import NotificationLog

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
    source: Optional[str] = None,
    notification_type: Optional[str] = None,
) -> List[NotificationLog]:
    """
    Return recent notification_log rows for a farm, optionally filtered by source and/or notification_type.

    **Input (request):**
        - session: AsyncSession.
        - farm_id: Farm UUID to filter by.
        - limit: Max number of rows (default 50).
        - source: Optional filter (e.g. "class_monitoring").
        - notification_type: Optional filter (e.g. "STATUS_CHANGE").

    **Output (response):**
        - List of NotificationLog instances ordered by created_at DESC.
    """
    stmt = (
        select(NotificationLog)
        .where(NotificationLog.farm_id == farm_id)
        .order_by(NotificationLog.created_at.desc())
        .limit(limit)
    )
    if source is not None:
        stmt = stmt.where(NotificationLog.source == source)
    if notification_type is not None:
        stmt = stmt.where(NotificationLog.notification_type == notification_type)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())
