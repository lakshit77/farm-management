"""Pydantic schemas for the all-show-entries list and selection endpoints."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class AllEntryItem(BaseModel):
    """Single entry in the all-show-entries list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    horse_name: str
    horse_id: str
    back_number: Optional[str] = None
    rider_list: Optional[str] = None
    trainer_name: Optional[str] = None
    owner_name: Optional[str] = None
    is_own_entry: bool
    is_selected: bool
    status: str
    api_entry_id: Optional[int] = None


class AllEntriesListData(BaseModel):
    """Paginated response for the all-show-entries list."""

    entries: List[AllEntryItem]
    total_count: int
    page: int
    page_size: int
    show_id: Optional[str] = None
    show_name: Optional[str] = None
