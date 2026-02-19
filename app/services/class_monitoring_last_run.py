"""
Format class monitoring last run timestamp for display (America/New_York).

The last run time is stored per farm in farms.class_monitoring_last_run_at (UTC).
This module provides formatting only; callers read from the farm and pass the datetime.
"""

from datetime import datetime
from typing import Optional

from zoneinfo import ZoneInfo

# America/New_York for display
NY_TZ = ZoneInfo("America/New_York")


def format_last_run_at_for_display(dt: Optional[datetime]) -> Optional[str]:
    """
    Format a UTC datetime as full human-readable last run time in America/New_York.

    **Input:** dt — UTC datetime from farm.class_monitoring_last_run_at, or None.

    **Output:** e.g. "Wed, 19 Feb 2026, 10:30 AM EST", or None if dt is None.
    """
    if dt is None:
        return None
    ny_time = dt.astimezone(NY_TZ)
    return ny_time.strftime("%a, %d %b %Y, %I:%M %p %Z")
