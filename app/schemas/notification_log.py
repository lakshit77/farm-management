"""Pydantic schemas for notification log API."""

from decimal import Decimal
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer


def _make_jsonable(obj: Any) -> Any:
    """Recursively convert Decimal and other non-JSON types for API response."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _make_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_jsonable(v) for v in obj]
    return obj


class NotificationLogItem(BaseModel):
    """Single notification log row for API response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    source: str
    notification_type: str
    message: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    entry_id: Optional[UUID] = None
    created_at: datetime

    @field_serializer("payload")
    def serialize_payload(self, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return None
        return _make_jsonable(v)


class NotificationLogListData(BaseModel):
    """Response data for GET /schedule/notifications."""

    notifications: List[NotificationLogItem]
