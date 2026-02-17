"""Pydantic schemas for schedule view API (events → classes → entries with horse, rider, status)."""

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class HorseView(BaseModel):
    """Horse details for schedule view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str


class RiderView(BaseModel):
    """Rider details for schedule view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str


class EntryView(BaseModel):
    """Entry details for schedule view: horse, rider, and backend status fields."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    horse: HorseView
    rider: Optional[RiderView] = None

    # Entry-level
    back_number: Optional[str] = None
    order_of_go: Optional[int] = None
    order_total: Optional[int] = None
    status: str = "active"
    scratch_trip: bool = False
    gone_in: bool = False

    # Class-level (duplicated per entry from backend)
    estimated_start: Optional[str] = None
    actual_start: Optional[str] = None
    scheduled_date: Optional[str] = None
    class_status: Optional[str] = None
    ring_status: Optional[str] = None
    total_trips: Optional[int] = None
    completed_trips: Optional[int] = None
    remaining_trips: Optional[int] = None

    # Results
    placing: Optional[int] = None
    points_earned: Optional[Decimal] = None
    total_prize_money: Optional[Decimal] = None
    faults_one: Optional[Decimal] = None
    time_one: Optional[Decimal] = None
    disqualify_status_one: Optional[str] = None
    faults_two: Optional[Decimal] = None
    time_two: Optional[Decimal] = None
    disqualify_status_two: Optional[str] = None
    score1: Optional[Decimal] = None
    score2: Optional[Decimal] = None
    score3: Optional[Decimal] = None
    score4: Optional[Decimal] = None
    score5: Optional[Decimal] = None
    score6: Optional[Decimal] = None


class ClassView(BaseModel):
    """Class details with entries (horse, rider, status) for schedule view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    class_number: Optional[str] = None
    sponsor: Optional[str] = None
    prize_money: Optional[Decimal] = None
    class_type: Optional[str] = None
    entries: List[EntryView] = []


class EventView(BaseModel):
    """Event (ring) with classes and entries for schedule view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    ring_number: Optional[int] = None
    classes: List[ClassView] = []


class ScheduleViewData(BaseModel):
    """Root payload for GET /schedule/view."""

    date: str
    show_name: Optional[str] = None
    show_id: Optional[str] = None
    events: List[EventView] = []
