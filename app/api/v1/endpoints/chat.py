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
    """Request body for generating a Stream Chat user token."""

    user_id: str = Field(
        ...,
        description="The Supabase user UUID. Used as the Stream Chat user ID.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    user_name: str = Field(
        ...,
        description="The display name shown in Stream Chat (e.g. the user's full name or email).",
        examples=["John Smith"],
    )
    role: str = Field(
        ...,
        description="The user's role in the application. One of: 'admin', 'manager', 'employee'.",
        examples=["admin"],
    )
    farm_id: str = Field(
        ...,
        description="The farm's UUID. Stored on the Stream user profile for channel scoping.",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )


class TokenResponse(BaseModel):
    """Stream Chat user token returned to the frontend."""

    token: str = Field(
        description=(
            "A short-lived Stream Chat JWT. Pass this to the Stream SDK's connectUser() call "
            "on the frontend. Tokens expire according to your Stream app settings."
        ),
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoiYWJjMTIzIn0.signature"],
    )


class SetupChannelsRequest(BaseModel):
    """Request body for creating or retrieving farm chat channels for a user."""

    user_id: str = Field(
        ...,
        description="The Supabase user UUID. Used to create the personal DM channel.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    role: str = Field(
        ...,
        description=(
            "The user's role. Only 'admin' users get an Admin-Only channel. "
            "All other roles receive All-Team and Personal DM channels only."
        ),
        examples=["admin"],
    )
    farm_id: str = Field(
        ...,
        description="The farm's UUID. All channel IDs are derived from this value.",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )


class SetupChannelsResponse(BaseModel):
    """Channel IDs created or confirmed for the user."""

    all_team_channel_id: str = Field(
        description=(
            "Stream channel ID for the farm-wide All-Team group. "
            "Format: farm-{first8hex(farm_id)}-all-team."
        ),
        examples=["farm-a1b2c3d4-all-team"],
    )
    admin_channel_id: Optional[str] = Field(
        default=None,
        description=(
            "Stream channel ID for the Admin-Only group. "
            "Null when the user's role is not 'admin'. "
            "Format: farm-{first8hex(farm_id)}-admin."
        ),
        examples=["farm-a1b2c3d4-admin"],
    )
    dm_channel_id: str = Field(
        description=(
            "Stream channel ID for the user's personal bot DM channel. "
            "Format: farm-{first8hex(farm_id)}-dm-{first8hex(user_id)}."
        ),
        examples=["farm-a1b2c3d4-dm-550e8400"],
    )


class SendMessageRequest(BaseModel):
    """Payload for sending a proactive bot message into a Stream Chat channel.

    Use this to push scheduled messages, alerts, or AI-generated reports from
    n8n (or any external service) into a farm's chat channel without a user
    triggering the flow.

    To attach action buttons to the message, include a ``custom`` dict with an
    ``actions`` list.  Each action must have ``id`` and ``label``; ``style`` is
    optional (``"primary"`` | ``"secondary"`` | ``"danger"``).  Example::

        {
            "actions": [
                {"id": "confirm", "label": "Yes, do it",  "style": "primary"},
                {"id": "cancel",  "label": "No, cancel",  "style": "secondary"}
            ],
            "action_context": {"intent": "delete_horse", "entry_id": "uuid"}
        }
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
            "Required when channel_context is 'dm'; ignored for 'all-team' and 'admin'. "
            "The Supabase UUID of the user whose personal DM channel should receive the message. "
            "In an n8n workflow triggered by the webhook, this is available as "
            "`{{ $json.user_id }}` from the incoming webhook payload."
        ),
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
    quoted_message_id: Optional[str] = Field(
        default=None,
        description=(
            "Stream message ID to quote-reply to. "
            "When set, the bot's message will appear with the original message quoted above it — "
            "identical to the 'swipe right to reply' behaviour in the mobile UI. "
            "Pass the 'message_id' that the webhook forwarded to n8n to have the bot reply "
            "directly to the user's message. "
            "Omit this field for a regular (non-quoted) message."
        ),
        examples=["b8e5f3c2-1234-5678-abcd-ef0123456789"],
    )
    custom: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional arbitrary metadata attached to the message. "
            "Use the 'actions' key to render interactive buttons inside the bot bubble on the frontend. "
            "Each action must have 'id' (machine key returned to n8n on click) and 'label' (button text). "
            "The optional 'style' field controls the button colour: "
            "'primary' = green fill, 'secondary' = grey outline, 'danger' = red fill. "
            "The 'action_context' key is an opaque JSON object forwarded unchanged to n8n when "
            "the user clicks — use it to carry the data your workflow needs to act on (e.g. entry IDs). "
            "When the user clicks a button, a new message is sent whose custom.action_reply contains "
            "action_id, action_context, and source_message_id. "
            "Omit this field entirely for plain text messages (fully backward compatible)."
        ),
        examples=[{
            "actions": [
                {"id": "confirm_delete", "label": "Yes, delete it", "style": "danger"},
                {"id": "cancel",         "label": "No, keep it",    "style": "secondary"},
            ],
            "action_context": {
                "intent": "delete_horse_entry",
                "horse_name": "CHECKPOINT",
                "entry_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        }],
    )


class SendMessageResponse(BaseModel):
    """Confirmation that the message was accepted and posted by Stream Chat."""

    channel_id: str = Field(
        description="The Stream channel ID the message was posted to.",
        examples=["farm-a1b2c3d4-all-team"],
    )
    bot: str = Field(
        description="The Stream user ID of the bot that sent the message.",
        examples=["all-team-bot"],
    )
    message_id: str = Field(
        description="Stream's unique ID for the newly created message. Store this if you need to update or reference the message later.",
        examples=["b8e5f3c2-1234-5678-abcd-ef0123456789"],
    )


class WebhookResponse(BaseModel):
    """Acknowledgement returned by the webhook endpoint to Stream Chat."""

    status: str = Field(
        description="'ok' when the event was accepted and processed. 'ignored' when the event type is not handled.",
        examples=["ok"],
    )
    reason: Optional[str] = Field(
        default=None,
        description="Present only when status is 'ignored'. Explains why the event was skipped.",
        examples=["not a message.new event"],
    )


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
        "Upserts the authenticated user in Stream Chat and returns a short-lived JWT "
        "that the frontend passes to the Stream SDK's `connectUser()` call.\n\n"
        "This endpoint also keeps the user's Stream profile in sync (name, role, farm_id) "
        "on every call, so it is safe to call on every login.\n\n"
        "**Authentication:** requires `Authorization: Bearer <API_SECRET_KEY>` header."
    ),
    responses={
        200: {
            "description": "Token generated successfully.",
            "content": {
                "application/json": {
                    "example": {
                        "status": 1,
                        "message": "success",
                        "data": {
                            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoiYWJjMTIzIn0.signature",
                        },
                    }
                }
            },
        },
        401: {"description": "Missing or invalid Bearer token."},
        500: {"description": "Stream Chat SDK error."},
    },
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
        "Idempotently creates (or updates membership on) the farm's chat channels for the given user:\n\n"
        "- **All-Team** — farm-wide group, created for every user.\n"
        "- **Admin-Only** — admin-only group, created only when `role` is `'admin'`. "
        "  `admin_channel_id` is `null` for non-admin users.\n"
        "- **Personal DM** — one-to-one channel between the user and the personal bot.\n\n"
        "This endpoint is idempotent and safe to call on every login. If the channels already "
        "exist, membership is refreshed without duplicating data.\n\n"
        "**Authentication:** requires `Authorization: Bearer <API_SECRET_KEY>` header."
    ),
    responses={
        200: {
            "description": "Channels created or confirmed. Returns the Stream channel IDs.",
            "content": {
                "application/json": {
                    "examples": {
                        "admin_user": {
                            "summary": "Admin user — all three channels returned",
                            "value": {
                                "status": 1,
                                "message": "success",
                                "data": {
                                    "all_team_channel_id": "farm-a1b2c3d4-all-team",
                                    "admin_channel_id": "farm-a1b2c3d4-admin",
                                    "dm_channel_id": "farm-a1b2c3d4-dm-550e8400",
                                },
                            },
                        },
                        "non_admin_user": {
                            "summary": "Non-admin user — admin_channel_id is null",
                            "value": {
                                "status": 1,
                                "message": "success",
                                "data": {
                                    "all_team_channel_id": "farm-a1b2c3d4-all-team",
                                    "admin_channel_id": None,
                                    "dm_channel_id": "farm-a1b2c3d4-dm-550e8400",
                                },
                            },
                        },
                    }
                }
            },
        },
        401: {"description": "Missing or invalid Bearer token."},
        500: {"description": "Stream Chat SDK error."},
    },
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
        "- `dm` channel       → `personal-bot`\n\n"
        "**Quoted replies (optional):**\n"
        "Set `quoted_message_id` to the Stream message ID of any existing message to have the bot "
        "reply to it directly — identical to the 'swipe right to reply' behaviour in the mobile UI. "
        "The original message will appear quoted above the bot's reply.\n\n"
        "In an n8n workflow triggered by the webhook, the incoming payload already contains "
        "`message_id` — the ID of the user's message. Pass it back as `quoted_message_id` in "
        "the `/send-message` call to make the bot quote-reply to that specific message.\n\n"
        "Example for a **DM channel** (`user_id` is required when `channel_context` is `'dm'`):\n\n"
        "```json\n"
        "{\n"
        '  "farm_id": "{{ $json.farm_id }}",\n'
        '  "channel_context": "dm",\n'
        '  "user_id": "{{ $json.user_id }}",\n'
        '  "bot": "personal-bot",\n'
        '  "text": "Here is the answer...",\n'
        '  "quoted_message_id": "{{ $json.message_id }}"\n'
        "}\n"
        "```\n\n"
        "Example for an **all-team channel** (`user_id` is not needed):\n\n"
        "```json\n"
        "{\n"
        '  "farm_id": "{{ $json.farm_id }}",\n'
        '  "channel_context": "all-team",\n'
        '  "bot": "all-team-bot",\n'
        '  "text": "Here is the answer...",\n'
        '  "quoted_message_id": "{{ $json.message_id }}"\n'
        "}\n"
        "```\n\n"
        "Note: when a message is sent via the `/webhook` auto-reply path (i.e. n8n returns "
        "a `text` response directly), the backend automatically sets `quoted_message_id` to "
        "the triggering user message — no extra configuration needed for that flow.\n\n"
        "**Action buttons (optional):**\n"
        "Include a `custom` object with an `actions` array to render interactive buttons "
        "inside the bot bubble on the frontend. Each action requires `id` (machine key sent "
        "back to n8n on click) and `label` (button text). The optional `style` field controls "
        "the button colour: `primary` (green), `secondary` (grey), or `danger` (red).\n\n"
        "Example `custom` payload:\n"
        "```json\n"
        "{\n"
        '  "actions": [\n'
        '    {"id": "confirm", "label": "Yes, do it",  "style": "primary"},\n'
        '    {"id": "cancel",  "label": "No, cancel",  "style": "secondary"}\n'
        "  ],\n"
        '  "action_context": {"intent": "delete_horse", "entry_id": "uuid"}\n'
        "}\n"
        "```\n\n"
        "**What happens when the user clicks a button:**\n\n"
        "The frontend automatically sends two requests:\n\n"
        "1. A new channel message (triggers webhook → n8n):\n"
        "```json\n"
        "{\n"
        '  "text": "Yes, delete it",\n'
        '  "custom": {\n'
        '    "action_reply": {\n'
        '      "action_id": "confirm_delete",\n'
        '      "action_context": {"intent": "delete_horse_entry", "entry_id": "uuid"},\n'
        '      "source_message_id": "<id of this bot message>"\n'
        "    }\n"
        "  }\n"
        "}\n"
        "```\n\n"
        "2. An update to the original bot message to persist the disabled state (so buttons "
        "stay disabled across refresh and on all devices):\n"
        "```json\n"
        "{\n"
        '  "id": "<id of this bot message>",\n'
        '  "custom": {\n'
        '    "actions": [...],\n'
        '    "action_context": {...},\n'
        '    "actions_answered": true,\n'
        '    "selected_action_id": "confirm_delete"\n'
        "  }\n"
        "}\n"
        "```\n\n"
        "In n8n, check `{{ $json.message_custom.action_reply }}` to detect a button click. "
        "If it exists, use `action_id` to know which button was pressed and `action_context` "
        "to retrieve the data needed to act on it."
    ),
    responses={
        200: {
            "description": "Message accepted and posted to Stream Chat.",
            "content": {
                "application/json": {
                    "examples": {
                        "plain_message": {
                            "summary": "Plain text bot message posted successfully",
                            "value": {
                                "status": 1,
                                "message": "success",
                                "data": {
                                    "channel_id": "farm-a1b2c3d4-all-team",
                                    "bot": "all-team-bot",
                                    "message_id": "b8e5f3c2-1234-5678-abcd-ef0123456789",
                                },
                            },
                        },
                        "message_with_buttons": {
                            "summary": "Bot message with action buttons posted successfully",
                            "value": {
                                "status": 1,
                                "message": "success",
                                "data": {
                                    "channel_id": "farm-a1b2c3d4-dm-550e8400",
                                    "bot": "personal-bot",
                                    "message_id": "c9f6d4e3-5678-1234-efab-cd9012345678",
                                },
                            },
                        },
                    }
                }
            },
        },
        400: {
            "description": "Invalid request body.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "'user_id' is required when channel_context is 'dm'."
                    }
                }
            },
        },
        401: {
            "description": "Missing or invalid X-API-Key header.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid or missing X-API-Key header."}
                }
            },
        },
        500: {
            "description": "Stream Chat rejected the message.",
            "content": {
                "application/json": {
                    "example": {"detail": "Stream Chat error: <error details>"}
                }
            },
        },
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

    # Resolve the channel ID — all IDs use _short() (first 8 hex chars) to match
    # the deterministic IDs created by setup_channels via _channel_id()/_short().
    if body.channel_context == "all-team":
        channel_id = _channel_id(body.farm_id, "all-team")
    elif body.channel_context == "admin":
        channel_id = _channel_id(body.farm_id, "admin")
    else:  # dm
        if not body.user_id:
            raise HTTPException(
                status_code=400,
                detail="'user_id' is required when channel_context is 'dm'.",
            )
        channel_id = _channel_id(body.farm_id, f"dm-{_short(body.user_id)}")

    # Resolve the bot user ID from the settings (falls back to the request value)
    bot_id_map = {
        "all-team-bot": settings.STREAM_ALLTEAM_BOT_ID,
        "admin-bot": settings.STREAM_ADMIN_BOT_ID,
        "personal-bot": settings.STREAM_PERSONAL_BOT_ID,
    }
    bot_user_id = bot_id_map.get(body.bot, body.bot)

    client = get_stream_client()
    ch = client.channel("messaging", channel_id)

    msg_payload: dict[str, Any] = {"text": body.text}
    if body.quoted_message_id:
        msg_payload["quoted_message_id"] = body.quoted_message_id
    if body.custom:
        msg_payload["custom"] = body.custom

    try:
        response = ch.send_message(
            message=msg_payload,
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
    response_model=WebhookResponse,
    summary="Stream Chat webhook receiver",
    description=(
        "Receives `message.new` events pushed by Stream Chat. This URL must be registered "
        "in the Stream Dashboard under **Chat → Webhooks** with the `message.new` event enabled.\n\n"
        "**Processing pipeline:**\n"
        "1. Verifies the HMAC-SHA256 signature in the `X-Signature` header.\n"
        "2. Deduplicates by message ID (in-memory, cleared on restart).\n"
        "3. Skips messages authored by any of the three bot users.\n"
        "4. Detects the channel context (`all-team` / `admin` / `dm`) from the channel ID pattern.\n"
        "5. Forwards the event to the matching n8n webhook URL.\n"
        "6. Posts n8n's reply back into the same channel as the appropriate bot.\n\n"
        "**Payload forwarded to n8n:**\n"
        "```json\n"
        "{\n"
        '  "channel_id": "farm-a1b2c3d4-dm-550e8400",\n'
        '  "channel_context": "dm",\n'
        '  "farm_id": "a1b2c3d4",\n'
        '  "message_id": "msg-abc123",\n'
        '  "message_text": "delete horse CHECKPOINT",\n'
        '  "message_custom": {},\n'
        '  "user_id": "user-uuid",\n'
        '  "user_name": "John Smith",\n'
        '  "mentioned_users": []\n'
        "}\n"
        "```\n\n"
        "`message_custom` is empty `{}` for plain text messages. When the user clicks a bot "
        "action button it contains `action_reply` with `action_id`, `action_context`, and "
        "`source_message_id` — use this in n8n to distinguish button clicks from free-text.\n\n"
        "**Expected n8n response (plain text reply):**\n"
        "```json\n"
        '{ "text": "Here is the answer..." }\n'
        "```\n\n"
        "The bot automatically quote-replies to the user's message (sets `quoted_message_id` "
        "internally) so the reply is visually anchored to it in the UI — no extra config needed.\n\n"
        "**Expected n8n response (reply with action buttons):**\n"
        "```json\n"
        "{\n"
        '  "text": "Are you sure?",\n'
        '  "custom": {\n'
        '    "actions": [\n'
        '      {"id": "yes", "label": "Yes, do it", "style": "primary"},\n'
        '      {"id": "no",  "label": "Cancel",     "style": "secondary"}\n'
        "    ],\n"
        '    "action_context": {"intent": "delete_horse", "entry_id": "uuid"}\n'
        "  }\n"
        "}\n"
        "```\n\n"
        "**Button click — what n8n receives:**\n\n"
        "When a user clicks an action button, the frontend automatically sends a new channel "
        "message. Stream fires a `message.new` webhook for it, and the backend forwards it to "
        "n8n with `message_custom.action_reply` populated:\n\n"
        "```json\n"
        "{\n"
        '  "channel_id": "farm-a1b2c3d4-dm-550e8400",\n'
        '  "channel_context": "dm",\n'
        '  "farm_id": "a1b2c3d4",\n'
        '  "message_id": "msg-new-111",\n'
        '  "message_text": "Yes, delete it",\n'
        '  "message_custom": {\n'
        '    "action_reply": {\n'
        '      "action_id": "confirm_delete",\n'
        '      "action_context": {\n'
        '        "intent": "delete_horse_entry",\n'
        '        "horse_name": "CHECKPOINT",\n'
        '        "entry_id": "550e8400-e29b-41d4-a716-446655440000"\n'
        "      },\n"
        '      "source_message_id": "msg-original-bot-xyz"\n'
        "    }\n"
        "  },\n"
        '  "user_id": "user-uuid",\n'
        '  "user_name": "John Smith",\n'
        '  "mentioned_users": []\n'
        "}\n"
        "```\n\n"
        "Key fields in `message_custom.action_reply`:\n"
        "- `action_id` — the `id` of the button the user clicked (e.g. `'confirm_delete'`).\n"
        "- `action_context` — the opaque context blob you attached when the bot sent the buttons. "
        "Forwarded unchanged — use it to carry entry IDs, horse names, or any data your workflow needs.\n"
        "- `source_message_id` — the Stream message ID of the original bot message that contained the buttons.\n\n"
        "**Recommended n8n branch logic:**\n"
        "Add an IF node as the first step in your workflow:\n"
        "```\n"
        "Condition: {{ $json.message_custom.action_reply }} exists\n"
        "  → TRUE  → Button click handler (use action_id + action_context)\n"
        "  → FALSE → Free-text message handler (use message_text)\n"
        "```\n\n"
        "**Authentication:** Stream signs every webhook request with HMAC-SHA256 using your "
        "`STREAM_API_SECRET`. The signature is in the `X-Signature` header. Verification is "
        "skipped if `STREAM_API_SECRET` is not set in the backend `.env` (not recommended for production)."
    ),
    responses={
        200: {
            "description": "Event acknowledged. Always returns 200 so Stream does not retry.",
            "content": {
                "application/json": {
                    "examples": {
                        "processed_free_text": {
                            "summary": "Free-text user message — forwarded to n8n",
                            "value": {"status": "ok"},
                        },
                        "processed_button_click": {
                            "summary": "Button click — forwarded to n8n with action_reply",
                            "value": {"status": "ok"},
                        },
                        "ignored": {
                            "summary": "Event type not handled (e.g. reaction.new)",
                            "value": {
                                "status": "ignored",
                                "reason": "not a message.new event",
                            },
                        },
                    }
                }
            },
        },
        400: {
            "description": "Request body is not valid JSON.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid JSON payload"}
                }
            },
        },
        401: {
            "description": "HMAC-SHA256 signature verification failed.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid webhook signature"}
                }
            },
        },
    },
)
async def stream_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
) -> WebhookResponse:
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
        return WebhookResponse(status="ignored", reason="not a message.new event")

    # Process — respond 200 immediately so Stream does not retry
    try:
        await process_webhook_event(payload)
    except Exception as exc:
        logger.exception("chat_bot.process_webhook_event raised an error: %s", exc)

    return WebhookResponse(status="ok")
