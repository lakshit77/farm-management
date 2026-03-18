"""Chat endpoints: Stream Chat token generation, channel setup, webhook handler, and proactive messaging."""

import hashlib
import hmac
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.stream_client import get_stream_client
from app.schemas.response import ApiResponse, success_response
from app.services.chat_bot import process_webhook_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Request / response models ──────────────────────────────────────────────────


class TokenRequest(BaseModel):
    user_id: str
    user_name: str
    role: str
    farm_id: str


class TokenResponse(BaseModel):
    token: str


class SetupChannelsRequest(BaseModel):
    user_id: str
    role: str
    farm_id: str


class SetupChannelsResponse(BaseModel):
    all_team_channel_id: str
    admin_channel_id: Optional[str]
    dm_channel_id: str


class SendMessageRequest(BaseModel):
    """Payload for sending a proactive bot message into a Stream Chat channel.

    Use this to push scheduled messages, alerts, or AI-generated reports from
    n8n (or any external service) into a farm's chat channel without a user
    triggering the flow.
    """

    farm_id: str = Field(
        ...,
        description="The farm's UUID. Used to derive the deterministic channel ID.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    channel_context: Literal["all-team", "admin", "dm"] = Field(
        ...,
        description=(
            "Which channel to post into: "
            "'all-team' for the farm-wide group, "
            "'admin' for the admin-only group, "
            "'dm' for a user's personal bot channel."
        ),
        examples=["all-team"],
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The message text to post. Supports Stream's markdown-like formatting.",
        examples=["Good morning! Here is today's schedule summary."],
    )
    bot: Literal["all-team-bot", "admin-bot", "personal-bot"] = Field(
        ...,
        description=(
            "Which bot identity to post as. Should match the channel context: "
            "all-team-bot → all-team, admin-bot → admin, personal-bot → dm."
        ),
        examples=["all-team-bot"],
    )
    user_id: Optional[str] = Field(
        default=None,
        description=(
            "Required only when channel_context is 'dm'. "
            "The UUID of the user whose personal DM channel should receive the message."
        ),
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )


class SendMessageResponse(BaseModel):
    """Confirmation that the message was accepted by Stream Chat."""

    channel_id: str = Field(description="The Stream channel ID the message was posted to.")
    bot: str = Field(description="The bot user ID that sent the message.")
    message_id: str = Field(description="Stream's unique ID for the newly created message.")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _verify_stream_signature(body: bytes, signature: str, api_secret: str) -> bool:
    """Verify the HMAC-SHA256 signature Stream attaches to webhook requests."""
    expected = hmac.new(
        api_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _short(uuid: str) -> str:
    """Return the first 8 hex chars of a UUID (strip hyphens first)."""
    return uuid.replace("-", "")[:8]


def _channel_id(farm_id: str, suffix: str) -> str:
    """Build a deterministic channel ID scoped to a farm, within Stream's 64-char limit.

    Full UUIDs are 36 chars each; farm-{uuid}-dm-{uuid} would be 81 chars.
    We use the first 8 hex chars of each UUID — collision probability is ~1 in 4 billion,
    which is negligible for a single farm's user set.
    """
    return f"farm-{_short(farm_id)}-{suffix}"


def _ensure_channel(
    client: Any,
    channel_type: str,
    channel_id: str,
    creator_id: str,
    data: dict,
    extra_members: Optional[list] = None,
) -> None:
    """Create a channel (or update membership if it already exists).

    Stream's server-side create is idempotent — calling it again on an existing
    channel updates its data. We then explicitly call add_members so the user
    is always a member regardless of whether the channel was just created or
    already existed.
    """
    ch = client.channel(channel_type, channel_id)
    try:
        ch.create(user_id=creator_id, data=data)
    except Exception as exc:
        logger.debug("Channel %s create error (may already exist): %s", channel_id, exc)

    # Always ensure all intended members are in the channel.
    # Pass dicts with channel_role so regular users get member-level permissions.
    members_to_add = list(data.get("members", []))
    if extra_members:
        members_to_add.extend(extra_members)
    if members_to_add:
        try:
            member_dicts = [
                {"user_id": uid, "channel_role": "channel_member"}
                for uid in members_to_add
            ]
            ch.add_members(member_dicts)
        except Exception as exc:
            logger.debug("add_members on %s: %s", channel_id, exc)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post(
    "/token",
    response_model=ApiResponse[TokenResponse],
    summary="Get Stream Chat user token",
    description=(
        "Upserts the authenticated user in Stream Chat and returns a short-lived "
        "user token the frontend uses to connect. Requires the standard Bearer API key."
    ),
)
async def get_chat_token(body: TokenRequest) -> ApiResponse[TokenResponse]:
    client = get_stream_client()

    # Upsert the user in Stream so their profile is current
    client.upsert_users([
        {
            "id": body.user_id,
            "name": body.user_name,
            "role": "user",
            "app_role": body.role,
            "farm_id": body.farm_id,
        }
    ])

    token = client.create_token(body.user_id)
    return success_response(data=TokenResponse(token=token))


@router.post(
    "/setup-channels",
    response_model=ApiResponse[SetupChannelsResponse],
    summary="Create or get farm chat channels for a user",
    description=(
        "Idempotently creates the All-Team group, Admin-Only group (admins only), "
        "and Personal DM channel for the given user within their farm. "
        "Safe to call on every login."
    ),
)
async def setup_channels(body: SetupChannelsRequest) -> ApiResponse[SetupChannelsResponse]:
    settings = get_settings()
    client = get_stream_client()

    all_team_id = _channel_id(body.farm_id, "all-team")
    dm_id = _channel_id(body.farm_id, f"dm-{_short(body.user_id)}")
    admin_id = _channel_id(body.farm_id, "admin") if body.role == "admin" else None

    # All-Team group: every user + all-team-bot
    _ensure_channel(
        client,
        "messaging",
        all_team_id,
        creator_id=settings.STREAM_ALLTEAM_BOT_ID,
        data={
            "members": [body.user_id, settings.STREAM_ALLTEAM_BOT_ID],
            "name": "All Team",
            "farm_id": body.farm_id,
            "channel_context": "all-team",
        },
    )

    # Admin-Only group: admin users + admin-bot
    if admin_id:
        _ensure_channel(
            client,
            "messaging",
            admin_id,
            creator_id=settings.STREAM_ADMIN_BOT_ID,
            data={
                "members": [body.user_id, settings.STREAM_ADMIN_BOT_ID],
                "name": "Admin",
                "farm_id": body.farm_id,
                "channel_context": "admin",
            },
        )

    # Personal DM: user + personal-bot
    _ensure_channel(
        client,
        "messaging",
        dm_id,
        creator_id=settings.STREAM_PERSONAL_BOT_ID,
        data={
            "members": [body.user_id, settings.STREAM_PERSONAL_BOT_ID],
            "name": "Personal Assistant",
            "farm_id": body.farm_id,
            "channel_context": "dm",
        },
    )

    return success_response(
        data=SetupChannelsResponse(
            all_team_channel_id=all_team_id,
            admin_channel_id=admin_id,
            dm_channel_id=dm_id,
        )
    )


@router.post(
    "/send-message",
    response_model=ApiResponse[SendMessageResponse],
    summary="Send a proactive bot message to a farm channel",
    description=(
        "Allows an external service (e.g. n8n) to push a message into any farm chat channel "
        "on behalf of a bot — without a user triggering the flow. "
        "Typical use cases: scheduled daily summaries, event alerts, reminders, or AI-generated reports.\n\n"
        "**Authentication:** requires the `X-API-Key` header set to the value of `API_SECRET_KEY` in your `.env`.\n\n"
        "**Channel resolution:**\n"
        "- `all-team` → `farm-{compact_farm_id}-all-team`\n"
        "- `admin`    → `farm-{compact_farm_id}-admin`\n"
        "- `dm`       → `farm-{compact_farm_id}-dm-{short_user_id}` (requires `user_id`)\n\n"
        "**Bot mapping (recommended):**\n"
        "- `all-team` channel → `all-team-bot`\n"
        "- `admin` channel    → `admin-bot`\n"
        "- `dm` channel       → `personal-bot`"
    ),
    responses={
        200: {"description": "Message accepted and posted to Stream Chat."},
        400: {"description": "Invalid request — e.g. `user_id` missing for a DM channel."},
        401: {"description": "Missing or invalid `X-API-Key` header."},
        500: {"description": "Stream Chat rejected the message."},
    },
)
async def send_message(
    body: SendMessageRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> ApiResponse[SendMessageResponse]:
    settings = get_settings()

    # Authenticate the caller — reject if the key is configured but missing/wrong
    if settings.API_SECRET_KEY and x_api_key != settings.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")

    # Resolve the channel ID
    compact_farm = body.farm_id.replace("-", "")
    if body.channel_context == "all-team":
        channel_id = f"farm-{compact_farm}-all-team"
    elif body.channel_context == "admin":
        channel_id = f"farm-{compact_farm}-admin"
    else:  # dm
        if not body.user_id:
            raise HTTPException(
                status_code=400,
                detail="'user_id' is required when channel_context is 'dm'.",
            )
        short_user = body.user_id.replace("-", "")[:16]
        channel_id = f"farm-{compact_farm}-dm-{short_user}"

    # Resolve the bot user ID from the settings (falls back to the request value)
    bot_id_map = {
        "all-team-bot": settings.STREAM_ALLTEAM_BOT_ID,
        "admin-bot": settings.STREAM_ADMIN_BOT_ID,
        "personal-bot": settings.STREAM_PERSONAL_BOT_ID,
    }
    bot_user_id = bot_id_map.get(body.bot, body.bot)

    client = get_stream_client()
    ch = client.channel("messaging", channel_id)

    try:
        response = ch.send_message(
            message={"text": body.text},
            user_id=bot_user_id,
        )
    except Exception as exc:
        logger.exception("send_message: Stream rejected the message for channel %s: %s", channel_id, exc)
        raise HTTPException(status_code=500, detail=f"Stream Chat error: {exc}")

    message_id: str = response.get("message", {}).get("id", "")
    logger.info("send_message: posted to %s as %s (msg_id=%s)", channel_id, bot_user_id, message_id)

    return success_response(
        data=SendMessageResponse(
            channel_id=channel_id,
            bot=bot_user_id,
            message_id=message_id,
        )
    )


@router.post(
    "/webhook",
    summary="Stream Chat webhook receiver",
    description=(
        "Receives message.new events from Stream Chat. "
        "Verifies the HMAC signature, deduplicates, skips bot messages, "
        "then routes to the appropriate n8n workflow via chat_bot.process_webhook_event."
    ),
)
async def stream_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
) -> dict[str, Any]:
    settings = get_settings()
    body = await request.body()

    # Verify webhook signature when the secret is configured
    if settings.STREAM_API_SECRET and x_signature:
        if not _verify_stream_signature(body, x_signature, settings.STREAM_API_SECRET):
            logger.warning("Stream webhook: invalid signature — request rejected")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("type", "")
    if event_type != "message.new":
        return {"status": "ignored", "reason": "not a message.new event"}

    # Process — respond 200 immediately so Stream does not retry
    try:
        await process_webhook_event(payload)
    except Exception as exc:
        logger.exception("chat_bot.process_webhook_event raised an error: %s", exc)

    return {"status": "ok"}
