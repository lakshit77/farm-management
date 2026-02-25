"""Notification log model for persisting change events from class monitoring and future flows."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import ForeignKey, String, Text, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from app.core.config import get_settings
from app.core.database import Base
from app.models.base import ts_created, uuid_pk


# Import for selectinload when loading entry relations (avoid circular import at use site)
from app.models.entry import Entry  # noqa: PLC0415


class NotificationLog(Base):
    """
    Log of all change notifications from class monitoring and future flows (e.g. horse availability).

    Show, class, and horse can be resolved via the optional entry relationship when needed.
    """

    __tablename__ = "notification_log"
    __table_args__ = (
        {
            "comment": "Log of all change notifications from class monitoring and future flows (horse availability, etc.).",
        },
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    farm_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    entry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = ts_created()

    entry = relationship("Entry", backref="notification_logs")


# -----------------------------------------------------------------------------
# DB operations (session passed by caller)
# -----------------------------------------------------------------------------


async def get_recent_notifications(
    session: AsyncSession,
    farm_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    source: Optional[str] = None,
    notification_type: Optional[str] = None,
    date_filter: Optional[date] = None,
    load_entry_relations: bool = False,
) -> List[NotificationLog]:
    """
    Return recent notification_log rows for a farm, optionally filtered by source,
    type, and date. Optionally load entry with horse and show_class for post-filtering.

    **Input (request):**
        - session: AsyncSession (caller-owned).
        - farm_id: Farm UUID to filter by.
        - limit: Max number of rows (default 50).
        - offset: Number of rows to skip (default 0), for pagination.
        - source: Optional filter (e.g. "class_monitoring").
        - notification_type: Optional filter (e.g. "STATUS_CHANGE").
        - date_filter: Optional single date. When set, notifications are filtered by
          *schedule day*: for rows with entry_id, the linked entry's scheduled_date must
          equal date_filter (so class monitoring run for Feb 22 shows under Feb 22);
          for rows without entry_id, created_at is matched to that day in VENUE_TIMEZONE.
        - load_entry_relations: If True, load entry.horse and entry.show_class.

    **Output (response):**
        - List of NotificationLog instances ordered by created_at DESC.
    """
    stmt = (
        select(NotificationLog)
        .where(NotificationLog.farm_id == farm_id)
        .order_by(NotificationLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if source is not None:
        stmt = stmt.where(NotificationLog.source == source)
    if notification_type is not None:
        stmt = stmt.where(NotificationLog.notification_type == notification_type)
    if date_filter is not None:
        # Filter by schedule day: notifications with an entry use the entry's
        # scheduled_date (so class monitoring for Feb 22 appears under Feb 22);
        # notifications without an entry use created_at in venue-timezone day.
        venue_tz = ZoneInfo(get_settings().VENUE_TIMEZONE)
        start_venue = datetime.combine(date_filter, time.min).replace(tzinfo=venue_tz)
        end_venue = datetime.combine(date_filter, time(23, 59, 59, 999999)).replace(tzinfo=venue_tz)
        start_utc = start_venue.astimezone(timezone.utc)
        end_utc = end_venue.astimezone(timezone.utc)
        stmt = stmt.outerjoin(Entry, NotificationLog.entry_id == Entry.id)
        stmt = stmt.where(
            or_(
                (NotificationLog.entry_id.isnot(None)) & (Entry.scheduled_date == date_filter),
                (NotificationLog.entry_id.is_(None))
                & (NotificationLog.created_at >= start_utc)
                & (NotificationLog.created_at <= end_utc),
            )
        )
    if load_entry_relations:
        stmt = stmt.options(
            selectinload(NotificationLog.entry).selectinload(Entry.horse),
            selectinload(NotificationLog.entry).selectinload(Entry.show_class),
        )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())
