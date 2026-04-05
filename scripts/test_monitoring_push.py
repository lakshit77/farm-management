#!/usr/bin/env python3
"""Manual harness for testing class-monitoring-style web pushes and morning summary.

Edit the **CONFIG** block below, then run from ``showgroundlive_monitoring`` root::

    python scripts/test_monitoring_push.py

Uses the same helpers as production so ``user_notification_preferences`` apply.

Set **TARGET_USER_ID** to your Supabase auth UUID to send only to yourself; leave it
``None`` to notify every eligible subscriber on the farm (not recommended when
clients have overlapping categories enabled).

**Note:** The push builder reads ``new_time`` for time-change bodies (not ``new``).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from typing import Any, Dict, List, Literal, Optional, Sequence

# Project root on path (same pattern as scripts/check_db_connection.py)
sys.path.insert(0, ".")

from app.core.enums import NotificationType
from app.services.push_notifications import notify_monitoring_changes, notify_morning_summary

MonitoringNotificationKind = Literal[
    "progress",
    "status_started",
    "status_completed",
    "time_change",
    "result",
    "horse_completed",
    "scratched",
    "morning_summary",
]

# ── CONFIG: edit these values only ─────────────────────────────────────────────

# Target farm (must match ``push_subscriptions.farm_id`` for your device).
FARM_ID: str = "191798cf-60b1-4398-99ef-775b64b658b5"

# Supabase auth ``sub`` for the only user who should receive this test push.
# Use None to broadcast to all eligible subscribers on the farm (everyone with
# push + that category enabled).
TARGET_USER_ID: Optional[str] = "c5ebec04-6f2e-4ea3-846d-cf8e845a3041"

# Pick one: progress | status_started | status_completed | time_change |
# result | horse_completed | scratched | morning_summary
NOTIFICATION_KIND: MonitoringNotificationKind = "result"

# Shared sample strings (used where relevant for the chosen kind).
SAMPLE_CLASS_NAME: str = "Test Class 1.20m"
SAMPLE_HORSE_NAME: str = "Demo Horse"
SAMPLE_RING_NAME: str = "Ring 1"

# PROGRESS_UPDATE
SAMPLE_PROGRESS_COMPLETED: int = 3
SAMPLE_PROGRESS_TOTAL: int = 12

# TIME_CHANGE (push layer uses this key in the change dict)
SAMPLE_NEW_TIME: str = "09:45"

# RESULT
SAMPLE_PLACING: int = 2

# STATUS_CHANGE — "Underway" / "In Progress" → Class Started; otherwise Class Completed
SAMPLE_STATUS_STARTED: str = "Underway"
SAMPLE_STATUS_COMPLETED: str = "Completed"

# MORNING_SUMMARY (ignored for other kinds)
SAMPLE_MORNING_CLASS_COUNT: int = 5
SAMPLE_MORNING_HORSE_COUNT: int = 8
SAMPLE_MORNING_FIRST_CLASS_TIME: Optional[str] = "08:30"  # or None

# ── end CONFIG ─────────────────────────────────────────────────────────────────


def _restrict_to_user_ids() -> Optional[Sequence[str]]:
    """Return a single-user restriction list when ``TARGET_USER_ID`` is set.

    Returns:
        A one-element sequence for ``notify_*`` restrict parameters, or ``None``
        when tests should use the default farm-wide recipient set.
    """
    if TARGET_USER_ID is None:
        return None
    uid = TARGET_USER_ID.strip()
    if not uid:
        return None
    return [uid]


def build_sample_changes(
    kind: MonitoringNotificationKind,
    *,
    class_name: str,
    horse_name: str,
    ring_name: str,
    progress_completed: int,
    progress_total: int,
    new_time: str,
    placing: int,
    new_status_started: str,
    new_status_completed: str,
) -> List[Dict[str, Any]]:
    """Return one synthetic change dict matching ``_build_monitoring_notification`` inputs.

    Args:
        kind: Which monitoring notification shape to build.
        class_name: Class label in the push body.
        horse_name: Horse name for entry-level notifications.
        ring_name: Ring label (optional in bodies).
        progress_completed: Completed trips for PROGRESS_UPDATE.
        progress_total: Total trips for PROGRESS_UPDATE.
        new_time: Shown after "now at" for TIME_CHANGE.
        placing: Numeric place for RESULT.
        new_status_started: Status string for Class Started (e.g. ``Underway``).
        new_status_completed: Status string for Class Completed (e.g. ``Completed``).

    Returns:
        A single-element list suitable for ``notify_monitoring_changes``.

    Raises:
        ValueError: If ``kind`` is ``morning_summary``.
    """
    if kind == "morning_summary":
        raise ValueError("morning_summary is handled by notify_morning_summary, not change dicts.")

    if kind == "progress":
        return [
            {
                "type": NotificationType.PROGRESS_UPDATE.value,
                "completed": progress_completed,
                "total": progress_total,
                "class_name": class_name,
                "ring_name": ring_name,
            }
        ]

    if kind == "status_started":
        return [
            {
                "type": NotificationType.STATUS_CHANGE.value,
                "new_status": new_status_started,
                "class_name": class_name,
                "ring_name": ring_name,
            }
        ]

    if kind == "status_completed":
        return [
            {
                "type": NotificationType.STATUS_CHANGE.value,
                "new_status": new_status_completed,
                "class_name": class_name,
                "ring_name": ring_name,
            }
        ]

    if kind == "time_change":
        return [
            {
                "type": NotificationType.TIME_CHANGE.value,
                "horse": horse_name,
                "class_name": class_name,
                "new_time": new_time,
                "ring_name": ring_name,
            }
        ]

    if kind == "result":
        return [
            {
                "type": NotificationType.RESULT.value,
                "horse": horse_name,
                "placing": placing,
                "prize_money": None,
                "class_name": class_name,
            }
        ]

    if kind == "horse_completed":
        return [
            {
                "type": NotificationType.HORSE_COMPLETED.value,
                "horse": horse_name,
                "class_name": class_name,
                "ring_name": ring_name,
            }
        ]

    if kind == "scratched":
        return [
            {
                "type": NotificationType.SCRATCHED.value,
                "horse": horse_name,
                "class_name": class_name,
            }
        ]

    raise ValueError(f"Unknown kind: {kind}")


async def run_test() -> None:
    """Read CONFIG constants and dispatch the selected test push."""
    try:
        farm_uuid = uuid.UUID(FARM_ID.strip())
    except ValueError as exc:
        raise SystemExit(
            f"Invalid FARM_ID in CONFIG: {FARM_ID!r}. Set a real farm UUID."
        ) from exc

    kind: MonitoringNotificationKind = NOTIFICATION_KIND
    restrict = _restrict_to_user_ids()

    print(
        f"[test_monitoring_push] farm_id={farm_uuid}\n"
        f"[test_monitoring_push] notification={kind!r}\n"
        f"[test_monitoring_push] restrict_to_user_ids={restrict!r} "
        f"(only these users considered; None = all subscribers on farm)"
    )

    if kind == "morning_summary":
        await notify_morning_summary(
            farm_id=farm_uuid,
            class_count=SAMPLE_MORNING_CLASS_COUNT,
            horse_count=SAMPLE_MORNING_HORSE_COUNT,
            first_class_time=SAMPLE_MORNING_FIRST_CLASS_TIME,
            restrict_to_user_ids=restrict,
        )
        print(
            "[test_monitoring_push] Sent morning_summary request "
            f"(classes={SAMPLE_MORNING_CLASS_COUNT}, horses={SAMPLE_MORNING_HORSE_COUNT})."
        )
        return

    changes = build_sample_changes(
        kind,
        class_name=SAMPLE_CLASS_NAME,
        horse_name=SAMPLE_HORSE_NAME,
        ring_name=SAMPLE_RING_NAME,
        progress_completed=SAMPLE_PROGRESS_COMPLETED,
        progress_total=SAMPLE_PROGRESS_TOTAL,
        new_time=SAMPLE_NEW_TIME,
        placing=SAMPLE_PLACING,
        new_status_started=SAMPLE_STATUS_STARTED,
        new_status_completed=SAMPLE_STATUS_COMPLETED,
    )
    await notify_monitoring_changes(
        farm_id=farm_uuid,
        changes=changes,
        restrict_to_user_ids=restrict,
    )
    print(f"[test_monitoring_push] Sent monitoring request; payload change(s): {changes!r}")


def main() -> None:
    """Configure logging for app/push libraries, then run the async test from CONFIG."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run_test())
    print(
        "[test_monitoring_push] Done. If no push arrived: check category prefs, "
        "subscription row for this farm, and any INFO lines above from app.services.push_notifications."
    )


if __name__ == "__main__":
    main()
