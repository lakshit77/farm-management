"""Base model and shared column types for SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID primary key. Default applied in Python; DB migration uses uuid_generate_v4()."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


def ts_created() -> Mapped[datetime]:
    """Timestamp for created_at (timezone-aware)."""
    return mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    )


def ts_updated() -> Mapped[Optional[datetime]]:
    """Timestamp for updated_at (timezone-aware)."""
    return mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


def jsonb_col() -> Mapped[Optional[dict]]:
    """JSONB column for metadata/settings."""
    return mapped_column(JSONB, nullable=True)
