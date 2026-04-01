"""Web Push notification service.

Handles sending VAPID-signed push notifications to subscribed browser devices.
Integrates with two trigger sources:
  - Stream Chat webhook (chat messages) via notify_chat_message()
  - Class monitoring (every 10 min) via notify_monitoring_changes()
  - Daily morning sync (Flow 1) via notify_morning_summary()

Each device that has opted in has a row in push_subscriptions.
Per-user category preferences are stored in user_notification_preferences.

Push delivery: pywebpush signs the payload with the VAPID private key and
POSTs it to the browser push service endpoint (Google FCM / Apple APNs).
On 410 Gone or 404, the subscription is marked inactive (device revoked).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.enums import NotificationType

logger = logging.getLogger(__name__)


# ── SQLAlchemy table references (inline to avoid circular imports) ──────────────
# We reference the tables via raw SQL text to keep this module import-clean.
# ORM models are defined in separate migration files; we query via text or
# simple select() with sa.table() shims below.

from sqlalchemy import Column, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import ts_created, uuid_pk


# ── ORM Models ─────────────────────────────────────────────────────────────────


class PushSubscription(Base):
    """One browser/device Web Push subscription for one user."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False, index=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh_key: Mapped[str] = mapped_column(Text, nullable=False)
    auth_key: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = ts_created()
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserNotificationPreferences(Base):
    """Per-user notification category preferences (shared across all devices)."""

    __tablename__ = "user_notification_preferences"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Chat
    chat_all_team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    chat_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    chat_dm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Show events
    class_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    time_changes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    results: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    horse_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scratched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    progress_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    morning_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# ── Notification payload builder ───────────────────────────────────────────────


def _build_payload(
    title: str,
    body: str,
    url: str = "/",
    tag: Optional[str] = None,
    urgent: bool = False,
) -> str:
    """Build the JSON string sent as the push message body.

    Args:
        title: Notification title shown on the device.
        body: Notification body text.
        url: Deep-link URL to open when the user taps the notification.
        tag: Optional grouping tag (same tag replaces previous notification).
        urgent: If True, requireInteraction is set in the service worker.

    Returns:
        JSON-encoded string suitable for the push payload.
    """
    data: Dict[str, Any] = {
        "title": title,
        "body": body,
        "url": url,
        "urgent": urgent,
    }
    if tag:
        data["tag"] = tag
    return json.dumps(data)


# ── Low-level push sender ──────────────────────────────────────────────────────


async def _send_one(
    session: AsyncSession,
    subscription: PushSubscription,
    payload: str,
) -> None:
    """Send a push to a single device subscription.

    Runs pywebpush in a thread-pool executor to avoid blocking the event loop.
    On 410/404 (subscription expired/revoked), marks the row inactive.

    Args:
        session: Async DB session (caller-owned; used only for cleanup writes).
        subscription: The PushSubscription ORM row to send to.
        payload: JSON string (from _build_payload).
    """
    settings = get_settings()

    def _do_send() -> None:
        from pywebpush import webpush, WebPushException  # type: ignore[import]

        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh_key,
                    "auth": subscription.auth_key,
                },
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={
                "sub": settings.VAPID_EMAIL,
            },
        )

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_send)
        subscription.last_used_at = datetime.now(timezone.utc)
        session.add(subscription)
        logger.debug(
            "Push sent to user=%s endpoint=...%s",
            subscription.user_id,
            subscription.endpoint[-20:],
        )
    except Exception as exc:
        exc_str = str(exc)
        if "410" in exc_str or "404" in exc_str or "gone" in exc_str.lower():
            logger.info(
                "Push subscription expired (410/404) for user=%s — marking inactive",
                subscription.user_id,
            )
            subscription.is_active = False
            session.add(subscription)
        else:
            logger.error(
                "Failed to send push to user=%s: %s",
                subscription.user_id,
                exc,
            )


# ── Mid-level: send to a set of user IDs ──────────────────────────────────────


async def send_push_to_users(
    session: AsyncSession,
    user_ids: Sequence[str],
    payload: str,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Send a push notification to all active subscriptions for the given users.

    Args:
        session: Async DB session.
        user_ids: Supabase auth UIDs to notify.
        payload: JSON string push body (from _build_payload).
        exclude_user_id: Optional user_id to skip (e.g. the message sender).
    """
    if not user_ids:
        return

    filtered = [uid for uid in user_ids if uid != exclude_user_id]
    if not filtered:
        return

    result = await session.execute(
        select(PushSubscription).where(
            PushSubscription.user_id.in_(filtered),
            PushSubscription.is_active.is_(True),
        )
    )
    subscriptions = list(result.scalars().all())

    if not subscriptions:
        logger.debug("No active push subscriptions for users: %s", filtered)
        return

    # Fire all in parallel; each handles its own error/cleanup
    await asyncio.gather(*[_send_one(session, sub, payload) for sub in subscriptions])


# ── Mid-level: send to all users of a farm filtered by preference ──────────────


async def send_push_to_farm(
    session: AsyncSession,
    farm_id: uuid.UUID,
    payload: str,
    preference_key: str,
    restrict_to_user_ids: Optional[Sequence[str]] = None,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Send a push to farm users who have a given preference enabled.

    Args:
        session: Async DB session.
        farm_id: The farm UUID.
        payload: JSON string push body.
        preference_key: Column name on UserNotificationPreferences to check
            (e.g. "results", "chat_all_team"). If the user has this set to False,
            they are skipped.
        restrict_to_user_ids: If provided, only send to these user IDs (subset of farm).
        exclude_user_id: Skip this user (e.g. message sender).
    """
    prefs_result = await session.execute(
        select(UserNotificationPreferences).where(
            UserNotificationPreferences.farm_id == farm_id,
        )
    )
    all_prefs = list(prefs_result.scalars().all())

    # Build set of user_ids who have this preference enabled
    eligible: List[str] = []
    for prefs in all_prefs:
        if restrict_to_user_ids and prefs.user_id not in restrict_to_user_ids:
            continue
        if prefs.user_id == exclude_user_id:
            continue
        pref_value = getattr(prefs, preference_key, True)
        if pref_value:
            eligible.append(prefs.user_id)

    if not eligible and not all_prefs:
        # Fall back only when no preference rows exist yet; this handles users
        # who haven't visited the preferences page. If rows exist but no users
        # are eligible, treat that as an explicit opt-out and send nothing.
        subs_result = await session.execute(
            select(PushSubscription).where(
                PushSubscription.farm_id == farm_id,
                PushSubscription.is_active.is_(True),
                PushSubscription.user_id != (exclude_user_id or ""),
            )
        )
        subscriptions = list(subs_result.scalars().all())
        if not subscriptions:
            return
        await asyncio.gather(*[_send_one(session, sub, payload) for sub in subscriptions])
        return

    if not eligible:
        logger.info(
            "No eligible users for push preference_key=%s farm_id=%s; skipping send.",
            preference_key,
            farm_id,
        )
        return

    await send_push_to_users(
        session,
        eligible,
        payload,
        exclude_user_id=exclude_user_id,
    )


# ── High-level: notify for chat messages ──────────────────────────────────────


async def notify_chat_message(
    farm_id: uuid.UUID,
    channel_context: str,
    sender_id: str,
    sender_name: str,
    message_text: str,
    channel_id: str,
    dm_user_id: Optional[str] = None,
) -> None:
    """Send push notifications to channel members when a new chat message arrives.

    Called fire-and-forget from chat_bot.py after routing to n8n.
    Opens its own DB session so it does not block the webhook response.

    Args:
        farm_id: The farm UUID extracted from the channel ID.
        channel_context: "all-team" | "admin" | "dm".
        sender_id: Supabase/Stream user ID of the message author (excluded from recipients).
        sender_name: Display name of the sender.
        message_text: The raw message text (truncated to 120 chars in body).
        channel_id: Full channel ID string (used to build the deep-link URL).
        dm_user_id: For DM channels, the Supabase user ID of the channel owner.
            Push is restricted to only this user so other farm members do not
            receive notifications for someone else's private conversation.
    """
    # Map channel context to preference key and notification title
    context_map: Dict[str, tuple[str, str]] = {
        "all-team": ("chat_all_team", "All Team"),
        "admin": ("chat_admin", "Admin Channel"),
        "dm": ("chat_dm", sender_name),
    }
    preference_key, title = context_map.get(channel_context, ("chat_all_team", "All Team"))

    body_text = message_text[:120] if message_text else ""
    if channel_context != "dm":
        body = f"{sender_name}: {body_text}"
    else:
        body = body_text

    url = f"/?tab=chat&channel={channel_context}"
    tag = f"chat-{channel_context}"

    payload = _build_payload(title=title, body=body, url=url, tag=tag, urgent=False)

    logger.info(
        "[push] notify_chat_message: farm=%s context=%s preference_key=%s exclude_sender=%s",
        farm_id,
        channel_context,
        preference_key,
        sender_id,
    )

    # For DM channels restrict delivery to only the channel owner — other farm
    # members should never see push notifications for someone else's private chat.
    restrict_to: Optional[List[str]] = [dm_user_id] if dm_user_id else None

    async with AsyncSessionLocal() as session:
        try:
            await send_push_to_farm(
                session=session,
                farm_id=farm_id,
                payload=payload,
                preference_key=preference_key,
                restrict_to_user_ids=restrict_to,
                exclude_user_id=sender_id,
            )
            await session.commit()
            logger.info("[push] notify_chat_message committed for farm=%s", farm_id)
        except Exception as exc:
            logger.exception(
                "notify_chat_message failed for farm=%s channel=%s: %s",
                farm_id,
                channel_id,
                exc,
            )


# ── High-level: notify for class monitoring changes ───────────────────────────


# Maps NotificationType to (title_template, body_template, url, urgent, preference_key, who)
# "who" is "all" or "horse_users_and_admins" or "horse_users"
_MONITORING_NOTIFICATION_MAP: Dict[str, Dict[str, Any]] = {
    NotificationType.STATUS_CHANGE.value: {
        "preference_key": "class_status",
        "urgent": False,
        "url": "/?tab=classes",
        "tag_prefix": "status",
        "who": "all",
    },
    NotificationType.TIME_CHANGE.value: {
        "preference_key": "time_changes",
        "urgent": False,
        "url": "/?tab=classes",
        "tag_prefix": "time",
        "who": "all",
    },
    NotificationType.PROGRESS_UPDATE.value: {
        "preference_key": "progress_updates",
        "urgent": False,
        "url": "/?tab=classes",
        "tag_prefix": "progress",
        "who": "all",
    },
    NotificationType.RESULT.value: {
        "preference_key": "results",
        "urgent": True,
        "url": "/?tab=classes",
        "tag_prefix": "result",
        "who": "all",
    },
    NotificationType.HORSE_COMPLETED.value: {
        "preference_key": "horse_completed",
        "urgent": True,
        "url": "/?tab=overview",
        "tag_prefix": "horse_completed",
        "who": "all",
    },
    NotificationType.SCRATCHED.value: {
        "preference_key": "scratched",
        "urgent": True,
        "url": "/?tab=classes",
        "tag_prefix": "scratched",
        "who": "all",
    },
}


def _build_monitoring_notification(change: Dict[str, Any]) -> Optional[tuple[str, str, str, bool, str]]:
    """Build (title, body, url, urgent, preference_key) from a structured change dict.

    Args:
        change: Structured change dict from class_monitoring (has 'type' key).

    Returns:
        Tuple of (title, body, url, urgent, preference_key) or None if unknown type.
    """
    change_type = change.get("type", "")
    cfg = _MONITORING_NOTIFICATION_MAP.get(change_type)
    if not cfg:
        return None

    horse = change.get("horse", "Horse")
    class_name = change.get("class_name", "class")
    ring_name = change.get("ring_name", "")

    if change_type == NotificationType.STATUS_CHANGE.value:
        new_status = change.get("new_status", "")
        if "underway" in new_status.lower() or "in progress" in new_status.lower():
            title = "Class Started"
            body = f"{class_name} is now underway"
            if ring_name:
                body += f" in {ring_name}"
        else:
            title = "Class Completed"
            body = f"{class_name} has finished"
            if ring_name:
                body += f" in {ring_name}"

    elif change_type == NotificationType.TIME_CHANGE.value:
        new_time = change.get("new_time", "")
        title = "Time Change"
        body = f"{horse} in {class_name}"
        if new_time:
            body += f": now at {new_time}"

    elif change_type == NotificationType.PROGRESS_UPDATE.value:
        completed = change.get("completed", "")
        total = change.get("total", "")
        title = "Class Progress"
        body = f"{class_name}: {completed}/{total} trips done"

    elif change_type == NotificationType.RESULT.value:
        placing = change.get("placing", "")
        title = "Result Posted"
        body = f"{horse}: {placing} place in {class_name}"

    elif change_type == NotificationType.HORSE_COMPLETED.value:
        title = "Horse Completed"
        body = f"{horse} finished {class_name}"
        if ring_name:
            body += f" in {ring_name}"

    elif change_type == NotificationType.SCRATCHED.value:
        title = "Horse Scratched"
        body = f"{horse} scratched from {class_name}"

    else:
        return None

    return (
        title,
        body,
        cfg["url"],
        cfg["urgent"],
        cfg["preference_key"],
    )


async def notify_monitoring_changes(
    farm_id: uuid.UUID,
    changes: List[Dict[str, Any]],
) -> None:
    """Send push notifications for all changes detected in a class monitoring run.

    Called after all log_notification() calls in class_monitoring.py.
    Opens its own DB session.

    Args:
        farm_id: Farm UUID.
        changes: List of structured change dicts from _process_one_class_with_data.
    """
    if not changes:
        return

    async with AsyncSessionLocal() as session:
        try:
            for change in changes:
                result = _build_monitoring_notification(change)
                if result is None:
                    continue

                title, body, url, urgent, preference_key = result
                change_type = change.get("type", "unknown")
                tag = f"{change_type.lower()}-{change.get('class_name', '')}"

                payload = _build_payload(
                    title=title,
                    body=body,
                    url=url,
                    tag=tag,
                    urgent=urgent,
                )

                await send_push_to_farm(
                    session=session,
                    farm_id=farm_id,
                    payload=payload,
                    preference_key=preference_key,
                )

            await session.commit()
        except Exception as exc:
            logger.exception(
                "notify_monitoring_changes failed for farm=%s: %s",
                farm_id,
                exc,
            )


# ── High-level: morning summary (Flow 1) ──────────────────────────────────────


async def notify_morning_summary(
    farm_id: uuid.UUID,
    class_count: int,
    horse_count: int,
    first_class_time: Optional[str] = None,
) -> None:
    """Send a morning summary push notification after the daily sync completes.

    Args:
        farm_id: Farm UUID.
        class_count: Total number of classes scheduled today.
        horse_count: Total number of horses entered today.
        first_class_time: Optional time string for the first class (e.g. "08:30").
    """
    body = f"{class_count} classes today, {horse_count} horses entered."
    if first_class_time:
        body += f" First class at {first_class_time}."

    payload = _build_payload(
        title="Good Morning — Today's Schedule",
        body=body,
        url="/?tab=overview",
        tag="morning-summary",
        urgent=False,
    )

    async with AsyncSessionLocal() as session:
        try:
            await send_push_to_farm(
                session=session,
                farm_id=farm_id,
                payload=payload,
                preference_key="morning_summary",
            )
            await session.commit()
        except Exception as exc:
            logger.exception(
                "notify_morning_summary failed for farm=%s: %s",
                farm_id,
                exc,
            )
