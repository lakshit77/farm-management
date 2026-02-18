"""Notification log model for persisting change events from class monitoring and future flows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import ts_created, uuid_pk


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
