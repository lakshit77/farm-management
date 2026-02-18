"""
Centralized enums for repeated string values used across the backend.

All logic that previously used hardcoded status/type strings should reference
these enums to avoid typos and ensure consistency. Use .value when a string
is required (e.g. for DB columns or API payloads).
"""

from enum import Enum


# -----------------------------------------------------------------------------
# Entry / entity status (entries, horses, schedule view)
# -----------------------------------------------------------------------------


class EntryStatus(str, Enum):
    """
    Status of an entry or entity (entry, horse) in the system.

    Used in Entry.status, Horse.status, schedule view defaults, and
    class monitoring derived status (_entry_status).
    """

    ACTIVE = "active"
    COMPLETED = "completed"
    SCRATCHED = "scratched"
    INACTIVE = "inactive"  # Entry in "my entries" but not in any class (not participating)


# -----------------------------------------------------------------------------
# Class status (Wellington API / class_status field on entries)
# -----------------------------------------------------------------------------


class ClassStatus(str, Enum):
    """
    Class-level status from Wellington API (class_related_data.status).

    Used when filtering active entries and when building STATUS_CHANGE alerts.
    """

    NOT_STARTED = "Not Started"
    UNDERWAY = "Underway"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"


# -----------------------------------------------------------------------------
# Notification log: source and type
# -----------------------------------------------------------------------------


class NotificationSource(str, Enum):
    """
    Origin of a notification log entry (e.g. which flow produced it).

    Stored in notification_log.source; used when logging and filtering.
    """

    CLASS_MONITORING = "class_monitoring"
    HORSE_AVAILABILITY = "horse_availability"


class NotificationType(str, Enum):
    """
    Kind of notification event (status change, time change, result, etc.).

    Stored in notification_log.notification_type; used when logging and
    when building alerts in class monitoring.
    """

    STATUS_CHANGE = "STATUS_CHANGE"
    TIME_CHANGE = "TIME_CHANGE"
    PROGRESS_UPDATE = "PROGRESS_UPDATE"
    RESULT = "RESULT"
    HORSE_COMPLETED = "HORSE_COMPLETED"
    SCRATCHED = "SCRATCHED"


# -----------------------------------------------------------------------------
# Schedule / Flow 1 response (task and trigger)
# -----------------------------------------------------------------------------


class ScheduleTaskResult(str, Enum):
    """Task result key in Flow 1 (daily schedule) API response."""

    COMPLETED = "completed"


class ScheduleTriggerType(str, Enum):
    """Trigger type in Flow 1 (daily schedule) API response."""

    DAILY = "daily"


# -----------------------------------------------------------------------------
# API response message
# -----------------------------------------------------------------------------


class ApiResponseMessage(str, Enum):
    """Default message for successful API responses."""

    SUCCESS = "success"
