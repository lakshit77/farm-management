"""Bot routing service for Stream Chat webhooks.

Receives a parsed message.new event, determines which channel context it came
from (all-team / admin / personal-DM), forwards the message to the matching
n8n webhook URL for AI processing, and posts the response back into the same
Stream channel as the correct bot user.

Channel ID naming convention (set by setup-channels endpoint):
  farm-{farmId}-all-team   ->  all-team-bot  ->  N8N_ALLTEAM_WEBHOOK_URL
  farm-{farmId}-admin      ->  admin-bot     ->  N8N_ADMIN_WEBHOOK_URL
  farm-{farmId}-dm-{uid}   ->  personal-bot  ->  N8N_PERSONAL_WEBHOOK_URL
"""

import logging
import re
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.core.stream_client import get_stream_client

logger = logging.getLogger(__name__)

# In-memory dedup set: stores recently processed message IDs to prevent
# double-processing on Stream webhook retries.  Cleared on restart (acceptable
# for this use-case; use a DB table for stronger guarantees).
_processed_message_ids: set[str] = set()
_MAX_DEDUP_SIZE = 10_000  # cap to avoid unbounded growth


# ── Channel-type detection ─────────────────────────────────────────────────────

_ALL_TEAM_RE = re.compile(r"^farm-[0-9a-f]{8}-all-team$")
_ADMIN_RE = re.compile(r"^farm-[0-9a-f]{8}-admin$")
_DM_RE = re.compile(r"^farm-[0-9a-f]{8}-dm-[0-9a-f]{8}$")


def _detect_channel_type(channel_id: str) -> Optional[str]:
    """Return 'all-team', 'admin', 'dm', or None if unrecognised."""
    if _ALL_TEAM_RE.match(channel_id):
        return "all-team"
    if _ADMIN_RE.match(channel_id):
        return "admin"
    if _DM_RE.match(channel_id):
        return "dm"
    return None


def _extract_farm_id(channel_id: str) -> Optional[str]:
    """Extract the farm UUID from a channel ID like farm-{farmId}-suffix."""
    parts = channel_id.split("-", 2)
    return parts[1] if len(parts) >= 2 else None


# ── Main entry point ───────────────────────────────────────────────────────────


async def process_webhook_event(event: dict[str, Any]) -> None:
    """Route a Stream message.new webhook event to the correct n8n workflow.

    Steps:
    1. Extract message details and guard against bot-authored messages.
    2. Dedup by message ID.
    3. Identify channel type from channel_id pattern.
    4. Forward to the matching n8n webhook URL.
    5. Post n8n's response back into the same channel as the correct bot.
    """
    settings = get_settings()

    # ── Extract fields ──────────────────────────────────────────────────────
    message: dict[str, Any] = event.get("message", {})
    message_id: str = message.get("id", "")
    message_text: str = message.get("text", "")
    # Stream stores extra fields sent via the JS/Python SDK under the
    # "custom" key.  However some SDK/API versions spread them at the
    # message root instead.  We read both locations for robustness.
    message_custom: dict[str, Any] = message.get("custom", {})

    logger.info(
        "[webhook] msg=%s  keys=%s  custom=%s",
        message_id,
        list(message.keys()),
        message_custom,
    )
    author: dict[str, Any] = message.get("user", {})
    author_id: str = author.get("id", "")
    author_name: str = author.get("name", author_id)
    mentioned_users: list[str] = [
        u.get("id", "") for u in message.get("mentioned_users", [])
    ]

    channel_id: str = event.get("channel_id", "")
    channel_type_raw: str = event.get("channel_type", "")  # Stream's type, e.g. "messaging"

    # ── Guard: skip messages authored by any of the three bots ─────────────
    bot_ids = {
        settings.STREAM_ALLTEAM_BOT_ID,
        settings.STREAM_ADMIN_BOT_ID,
        settings.STREAM_PERSONAL_BOT_ID,
    }
    if author_id in bot_ids:
        logger.debug("Skipping bot-authored message %s from %s", message_id, author_id)
        return

    # Skip system messages
    if message.get("type") == "system":
        return

    # ── Dedup ───────────────────────────────────────────────────────────────
    if message_id in _processed_message_ids:
        logger.debug("Duplicate webhook event for message %s — skipping", message_id)
        return

    _processed_message_ids.add(message_id)
    if len(_processed_message_ids) > _MAX_DEDUP_SIZE:
        # Evict oldest half when the set grows too large
        to_remove = list(_processed_message_ids)[: _MAX_DEDUP_SIZE // 2]
        for mid in to_remove:
            _processed_message_ids.discard(mid)

    # ── Persist action-button answered state on the original bot message ────
    # When a user clicks a bot action button, the frontend sends a message
    # with custom.action_reply.  The frontend cannot update the bot's own
    # message (permission denied), so the backend does it here using the
    # server-side client which has admin privileges.
    #
    # Stream might nest the data under message.custom or spread it at the
    # message root, so we check both.
    action_reply: Optional[dict[str, Any]] = (
        message_custom.get("action_reply")
        or message.get("action_reply")
    )
    logger.info(
        "[webhook] action_reply resolved to: %s (from custom: %s, from root: %s)",
        action_reply,
        message_custom.get("action_reply"),
        message.get("action_reply"),
    )
    if action_reply and isinstance(action_reply, dict):
        source_msg_id: str = action_reply.get("source_message_id", "")
        selected_action_id: str = action_reply.get("action_id", "")
        logger.info(
            "[action_reply] source_msg_id=%s  selected_action_id=%s",
            source_msg_id,
            selected_action_id,
        )
        if source_msg_id:
            try:
                client = get_stream_client()
                # Fetch the original bot message to:
                #  a) preserve its text and existing custom data,
                #  b) get the bot user_id (required by server-side auth).
                # NOTE: update_message_partial cannot touch the "custom"
                # field (Stream reserves it), so we must do a full update.
                original_resp = client.get_message(source_msg_id)
                original_msg: dict[str, Any] = original_resp.get("message", {})
                original_custom: dict[str, Any] = original_msg.get("custom", {})
                bot_uid: str = original_msg.get("user", {}).get("id", "")

                original_custom["actions_answered"] = True
                original_custom["selected_action_id"] = selected_action_id

                client.update_message({
                    "id": source_msg_id,
                    "text": original_msg.get("text", ""),
                    "user_id": bot_uid,
                    "custom": original_custom,
                })
                logger.info(
                    "Marked bot message %s as answered (action_id=%s, bot=%s)",
                    source_msg_id,
                    selected_action_id,
                    bot_uid,
                )
            except Exception as exc:
                logger.error(
                    "Failed to update bot message %s with answered state: %s",
                    source_msg_id,
                    exc,
                )

    # ── Identify channel context ────────────────────────────────────────────
    channel_context = _detect_channel_type(channel_id)
    if channel_context is None:
        logger.debug(
            "Message %s in unrecognised channel %s — skipping", message_id, channel_id
        )
        return

    farm_id = _extract_farm_id(channel_id)

    # Map channel context -> (n8n URL, bot user ID)
    routing: dict[str, tuple[str, str]] = {
        "all-team": (settings.N8N_ALLTEAM_WEBHOOK_URL, settings.STREAM_ALLTEAM_BOT_ID),
        "admin": (settings.N8N_ADMIN_WEBHOOK_URL, settings.STREAM_ADMIN_BOT_ID),
        "dm": (settings.N8N_PERSONAL_WEBHOOK_URL, settings.STREAM_PERSONAL_BOT_ID),
    }
    n8n_url, bot_user_id = routing[channel_context]

    if not n8n_url:
        logger.warning(
            "No n8n webhook URL configured for channel context '%s' — skipping message %s",
            channel_context,
            message_id,
        )
        return

    # ── Forward to n8n ──────────────────────────────────────────────────────
    n8n_payload = {
        "channel_id": channel_id,
        "channel_context": channel_context,
        "farm_id": farm_id,
        "message_id": message_id,
        "message_text": message_text,
        # Forwarded verbatim so n8n can inspect action_reply on button clicks
        # or any other custom metadata attached by the frontend.
        "message_custom": message_custom,
        "user_id": author_id,
        "user_name": author_name,
        "mentioned_users": mentioned_users,
    }

    response_text: Optional[str] = None
    response_custom: Optional[dict[str, Any]] = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(n8n_url, json=n8n_payload)
            resp.raise_for_status()
            data = resp.json()
            # n8n should return { "text": "...", "custom": {...} } or a plain string.
            # The optional "custom" dict carries action buttons or other metadata
            # that the frontend renders inside the bot bubble.
            if isinstance(data, dict):
                response_text = data.get("text") or data.get("message") or data.get("output")
                response_custom = data.get("custom") if isinstance(data.get("custom"), dict) else None
            elif isinstance(data, str):
                response_text = data
    except httpx.TimeoutException:
        logger.error(
            "n8n webhook timed out for message %s (channel: %s)", message_id, channel_id
        )
        return
    except httpx.HTTPStatusError as exc:
        logger.error(
            "n8n webhook returned %s for message %s: %s",
            exc.response.status_code,
            message_id,
            exc.response.text,
        )
        return
    except Exception as exc:
        logger.exception("Unexpected error calling n8n for message %s: %s", message_id, exc)
        return

    if not response_text or not response_text.strip():
        logger.debug("n8n returned empty response for message %s — no bot reply sent", message_id)
        return

    # ── Post bot response into the same Stream channel ──────────────────────
    try:
        client = get_stream_client()
        ch = client.channel(channel_type_raw or "messaging", channel_id)
        msg_payload: dict[str, Any] = {"text": response_text.strip()}
        if response_custom:
            msg_payload["custom"] = response_custom
        ch.send_message(
            message=msg_payload,
            user_id=bot_user_id,
        )
        logger.info(
            "Bot '%s' replied in channel '%s' for message %s",
            bot_user_id,
            channel_id,
            message_id,
        )
    except Exception as exc:
        logger.exception(
            "Failed to send bot response in channel %s for message %s: %s",
            channel_id,
            message_id,
            exc,
        )
