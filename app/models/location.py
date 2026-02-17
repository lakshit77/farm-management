"""Location model (physical or event venue)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import ts_created, ts_updated, uuid_pk


class Location(Base):
    """Physical location or event venue."""

    __tablename__ = "locations"
    __table_args__ = (
        {"comment": "Physical locations (Farm, Vet, Event Venue)."},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    farm_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # "physical" or "event_venue"
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[Optional[datetime]] = ts_updated()

    farm = relationship("Farm", backref="locations")
