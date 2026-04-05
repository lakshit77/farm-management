"""Web Push notification endpoints.

Handles push subscription management, VAPID public key distribution,
notification preference management, and test push sending.

All mutating endpoints require a Supabase Bearer JWT in the Authorization header.
The user_id is extracted from the JWT sub claim.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import jwt as pyjwt
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.schemas.response import ApiResponse, success_response
from app.services.push_notifications import (
    PushSubscription,
    UserNotificationPreferences,
    _build_payload,
    _send_one,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push"])


# ── Auth helper ────────────────────────────────────────────────────────────────


def _extract_user_id(authorization: Optional[str]) -> str:
    """Extract the user_id (sub claim) from a Supabase Bearer JWT.

    Does NOT verify the JWT signature — signature verification would require
    the Supabase JWT secret. Instead we trust the token is valid (FastAPI backend
    is behind the Supabase-authenticated frontend). For production hardening,
    add SUPABASE_JWT_SECRET to config and verify the signature here.

    Args:
        authorization: Raw Authorization header value (e.g. "Bearer eyJ...").

    Returns:
        The user's UUID string from the JWT sub claim.

    Raises:
        HTTPException 401: If no/invalid Authorization header.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token> header.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        # Decode without verification to extract sub claim
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise HTTPException(status_code=401, detail="JWT missing sub claim.")
        return user_id
    except Exception as exc:
        logger.warning("JWT decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid JWT token.")


def _extract_farm_id(authorization: Optional[str]) -> Optional[str]:
    """Extract the farm_id claim from the JWT if present (set by frontend on token creation).

    Returns None if the claim is absent — caller must handle fallback.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = pyjwt.decode(token, options={"verify_signature": False})
        return payload.get("farm_id") or payload.get("user_metadata", {}).get("farm_id")
    except Exception:
        return None


# ── Request / response schemas ─────────────────────────────────────────────────


class SubscribeRequest(BaseModel):
    """Push subscription data returned by pushManager.subscribe() on the frontend."""

    endpoint: str = Field(
        ...,
        description="The unique push endpoint URL assigned by the browser push service (FCM/APNs).",
    )
    p256dh: str = Field(
        ...,
        description="The P-256 DH public key from the browser subscription (base64url-encoded).",
    )
    auth: str = Field(
        ...,
        description="The authentication secret from the browser subscription (base64url-encoded).",
    )
    farm_id: str = Field(
        ...,
        description="The farm UUID this user belongs to.",
    )
    user_agent: Optional[str] = Field(
        default=None,
        description="Optional device/browser hint for display in settings (e.g. 'iPhone / Safari 17').",
    )


class UnsubscribeRequest(BaseModel):
    """Request to deactivate a specific push subscription."""

    endpoint: str = Field(
        ...,
        description="The endpoint URL to deactivate. Must match the stored subscription.",
    )


class VapidKeyResponse(BaseModel):
    """VAPID public key for the frontend to use when calling pushManager.subscribe()."""

    public_key: str = Field(
        description="URL-safe base64-encoded VAPID public key (uncompressed P-256 point).",
    )


class PreferencesResponse(BaseModel):
    """Per-user notification category preferences."""

    user_id: str
    farm_id: str
    # Chat
    chat_all_team: bool
    chat_admin: bool
    chat_dm: bool
    # Show events
    class_status: bool
    time_changes: bool
    results: bool
    horse_completed: bool
    scratched: bool
    progress_updates: bool
    morning_summary: bool


class PreferencesUpdateRequest(BaseModel):
    """Partial update to notification preferences. Only provided fields are updated."""

    chat_all_team: Optional[bool] = None
    chat_admin: Optional[bool] = None
    chat_dm: Optional[bool] = None
    class_status: Optional[bool] = None
    time_changes: Optional[bool] = None
    results: Optional[bool] = None
    horse_completed: Optional[bool] = None
    scratched: Optional[bool] = None
    progress_updates: Optional[bool] = None
    morning_summary: Optional[bool] = None


class SubscribeResponse(BaseModel):
    """Confirmation that subscription was stored."""

    subscription_id: str = Field(description="UUID of the stored push subscription row.")


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/vapid-public-key",
    response_model=ApiResponse[VapidKeyResponse],
    summary="Get VAPID public key",
    description=(
        "Returns the VAPID public key required by the frontend to call "
        "`pushManager.subscribe({ applicationServerKey: publicKey })`. "
        "No authentication required."
    ),
)
async def get_vapid_public_key() -> ApiResponse[VapidKeyResponse]:
    """Return the VAPID public key for push subscription.

    Returns:
        ApiResponse containing the VAPID public key string.
    """
    settings = get_settings()
    if not settings.VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="Push notifications not configured on this server.")
    return success_response(data=VapidKeyResponse(public_key=settings.VAPID_PUBLIC_KEY))


@router.post(
    "/subscribe",
    response_model=ApiResponse[SubscribeResponse],
    summary="Store a push subscription",
    description=(
        "Upserts a browser push subscription for the authenticated user's device. "
        "Call this after `pushManager.subscribe()` succeeds on the frontend. "
        "If the endpoint already exists it is updated and re-activated. "
        "**Authentication:** `Authorization: Bearer <Supabase JWT>` required."
    ),
)
async def subscribe(
    body: SubscribeRequest,
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> ApiResponse[SubscribeResponse]:
    """Save or update a push subscription for the calling user's device.

    Args:
        body: Subscription data from the browser.
        authorization: Supabase Bearer JWT.

    Returns:
        ApiResponse with the stored subscription UUID.
    """
    user_id = _extract_user_id(authorization)

    try:
        farm_uuid = uuid.UUID(body.farm_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid farm_id UUID.")

    async with AsyncSessionLocal() as session:
        # Upsert: insert new or update existing on endpoint conflict
        stmt = (
            pg_insert(PushSubscription)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                farm_id=farm_uuid,
                endpoint=body.endpoint,
                p256dh_key=body.p256dh,
                auth_key=body.auth,
                user_agent=body.user_agent,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                last_used_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["endpoint"],
                set_={
                    "user_id": user_id,
                    "farm_id": farm_uuid,
                    "p256dh_key": body.p256dh,
                    "auth_key": body.auth,
                    "user_agent": body.user_agent,
                    "is_active": True,
                    "last_used_at": datetime.now(timezone.utc),
                },
            )
            .returning(PushSubscription.id)
        )
        result = await session.execute(stmt)
        row = result.fetchone()
        await session.commit()
        sub_id = str(row[0]) if row else ""

    logger.info("Push subscription stored for user=%s farm=%s", user_id, body.farm_id)
    return success_response(data=SubscribeResponse(subscription_id=sub_id))


@router.delete(
    "/subscribe",
    response_model=ApiResponse[None],
    summary="Deactivate a push subscription",
    description=(
        "Marks a specific device's push subscription as inactive. "
        "The device will no longer receive push notifications. "
        "The subscription row is kept for audit purposes. "
        "**Authentication:** `Authorization: Bearer <Supabase JWT>` required."
    ),
)
async def unsubscribe(
    body: UnsubscribeRequest,
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> ApiResponse[None]:
    """Deactivate a push subscription for the calling user.

    Args:
        body: Contains the endpoint URL to deactivate.
        authorization: Supabase Bearer JWT.

    Returns:
        ApiResponse with no data on success.
    """
    user_id = _extract_user_id(authorization)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == body.endpoint,
                PushSubscription.user_id == user_id,
            )
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            raise HTTPException(status_code=404, detail="Subscription not found for this user.")
        sub.is_active = False
        session.add(sub)
        await session.commit()

    logger.info("Push subscription deactivated for user=%s", user_id)
    return success_response()


@router.post(
    "/test",
    response_model=ApiResponse[Dict[str, Any]],
    summary="Send a test push notification",
    description=(
        "Sends a test push notification to all active subscriptions for the calling user. "
        "Useful during development and for verifying the subscription flow. "
        "**Authentication:** `Authorization: Bearer <Supabase JWT>` required."
    ),
)
async def test_push(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> ApiResponse[Dict[str, Any]]:
    """Fire a test push to all active subscriptions for the authenticated user.

    Args:
        authorization: Supabase Bearer JWT.

    Returns:
        ApiResponse with count of devices notified.
    """
    user_id = _extract_user_id(authorization)

    payload = _build_payload(
        title="Test Notification",
        body="Push notifications are working correctly.",
        url="/",
        tag="test",
    )

    sent = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PushSubscription).where(
                PushSubscription.user_id == user_id,
                PushSubscription.is_active.is_(True),
            )
        )
        subscriptions = list(result.scalars().all())

        for sub in subscriptions:
            await _send_one(session, sub, payload)
            sent += 1

        await session.commit()

    logger.info("Test push sent to %s device(s) for user=%s", sent, user_id)
    return success_response(data={"devices_notified": sent})


@router.get(
    "/preferences",
    response_model=ApiResponse[PreferencesResponse],
    summary="Get notification preferences",
    description=(
        "Returns the user's per-category notification preferences. "
        "If no preference row exists yet, one is created with all categories enabled. "
        "**Authentication:** `Authorization: Bearer <Supabase JWT>` required."
    ),
)
async def get_preferences(
    farm_id: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> ApiResponse[PreferencesResponse]:
    """Return (or auto-create) the notification preferences for the authenticated user.

    Args:
        farm_id: Farm UUID as a query parameter.
        authorization: Supabase Bearer JWT.

    Returns:
        ApiResponse containing the full preferences object.
    """
    user_id = _extract_user_id(authorization)

    try:
        farm_uuid = uuid.UUID(farm_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid farm_id UUID.")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserNotificationPreferences).where(
                UserNotificationPreferences.user_id == user_id,
            )
        )
        prefs = result.scalar_one_or_none()

        if prefs is None:
            # Auto-create with all defaults enabled
            prefs = UserNotificationPreferences(
                user_id=user_id,
                farm_id=farm_uuid,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(prefs)
            await session.commit()
            await session.refresh(prefs)

    return success_response(
        data=PreferencesResponse(
            user_id=prefs.user_id,
            farm_id=str(prefs.farm_id),
            chat_all_team=prefs.chat_all_team,
            chat_admin=prefs.chat_admin,
            chat_dm=prefs.chat_dm,
            class_status=prefs.class_status,
            time_changes=prefs.time_changes,
            results=prefs.results,
            horse_completed=prefs.horse_completed,
            scratched=prefs.scratched,
            progress_updates=prefs.progress_updates,
            morning_summary=prefs.morning_summary,
        )
    )


@router.put(
    "/preferences",
    response_model=ApiResponse[PreferencesResponse],
    summary="Update notification preferences",
    description=(
        "Partially updates the user's per-category notification preferences. "
        "Only the fields provided in the request body are updated; all others remain unchanged. "
        "Preferences apply to all devices for this user. "
        "**Authentication:** `Authorization: Bearer <Supabase JWT>` required."
    ),
)
async def update_preferences(
    body: PreferencesUpdateRequest,
    farm_id: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> ApiResponse[PreferencesResponse]:
    """Update one or more notification preference toggles for the authenticated user.

    Args:
        body: Partial update — only provided fields are changed.
        farm_id: Farm UUID as a query parameter.
        authorization: Supabase Bearer JWT.

    Returns:
        ApiResponse containing the updated preferences object.
    """
    user_id = _extract_user_id(authorization)

    try:
        farm_uuid = uuid.UUID(farm_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid farm_id UUID.")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserNotificationPreferences).where(
                UserNotificationPreferences.user_id == user_id,
            )
        )
        prefs = result.scalar_one_or_none()

        if prefs is None:
            prefs = UserNotificationPreferences(
                user_id=user_id,
                farm_id=farm_uuid,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(prefs)

        # Apply only the fields that were explicitly provided
        update_data = body.model_dump(exclude_none=True)
        for field, value in update_data.items():
            setattr(prefs, field, value)
        prefs.updated_at = datetime.now(timezone.utc)
        session.add(prefs)
        await session.commit()
        await session.refresh(prefs)

    logger.info("Notification preferences updated for user=%s: %s", user_id, update_data)
    return success_response(
        data=PreferencesResponse(
            user_id=prefs.user_id,
            farm_id=str(prefs.farm_id),
            chat_all_team=prefs.chat_all_team,
            chat_admin=prefs.chat_admin,
            chat_dm=prefs.chat_dm,
            class_status=prefs.class_status,
            time_changes=prefs.time_changes,
            results=prefs.results,
            horse_completed=prefs.horse_completed,
            scratched=prefs.scratched,
            progress_updates=prefs.progress_updates,
            morning_summary=prefs.morning_summary,
        )
    )
