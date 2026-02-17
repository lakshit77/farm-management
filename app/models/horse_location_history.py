"""Horse location history model. Tracks horse movements with context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.base import uuid_pk


class HorseLocationHistory(Base):
    """Tracks horse movements with context (show, event, class, entry)."""

    __tablename__ = "horse_location_history"
    __table_args__ = (
        {"comment": "Tracks horse movements with context."},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    horse_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("horses.id", ondelete="CASCADE"),
        nullable=False,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
    )
    show_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("shows.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    class_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"),
        nullable=True,
    )
    entry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    horse = relationship("Horse", backref="location_history")
    location = relationship("Location", backref="horse_location_history")
    show = relationship("Show", backref="horse_location_history")
    event = relationship("Event", backref="horse_location_history")
    show_class = relationship("ShowClass", backref="horse_location_history")
    entry = relationship("Entry", backref="horse_location_history")
