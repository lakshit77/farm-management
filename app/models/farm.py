"""Farm model (multi-tenant) and DB operations (caller passes session)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Integer, select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import jsonb_col, ts_created, ts_updated, uuid_pk


class Farm(Base):
    """Multi-tenant farm. customer_id links to external API."""

    __tablename__ = "farms"
    __table_args__ = {"comment": "Multi-tenant farm support. customer_id links to API."}

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    settings: Mapped[Optional[dict]] = jsonb_col()
    created_at: Mapped[datetime] = ts_created()
    updated_at: Mapped[Optional[datetime]] = ts_updated()


# -----------------------------------------------------------------------------
# DB operations (session passed by caller)
# -----------------------------------------------------------------------------


async def get_farm_by_name_and_customer(
    session: AsyncSession,
    name: str,
    customer_id: Optional[int],
) -> Optional[Farm]:
    """
    Return the farm with the given name and customer_id, or None if not found.
    """
    result = await session.execute(
        select(Farm).where(
            Farm.name == name,
            Farm.customer_id == customer_id,
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def create_farm(
    session: AsyncSession,
    name: str,
    customer_id: Optional[int] = None,
    settings: Optional[dict[str, Any]] = None,
) -> Farm:
    """
    Create a new farm and flush so id/created_at are available. Caller must commit.
    """
    farm = Farm(name=name, customer_id=customer_id, settings=settings)
    session.add(farm)
    await session.flush()
    await session.refresh(farm)
    return farm
