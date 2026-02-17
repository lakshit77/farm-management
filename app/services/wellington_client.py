"""
Wellington (ShowGroundsLive) external API client.

Uses Bearer token from login. All request/response handling for schedule and entries.
Requires Origin header (e.g. https://www.wellingtoninternational.com) for requests to succeed.
See docs/API_USAGE.md for API contract.
"""

import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings
from app.core.constants import ORIGIN

logger = logging.getLogger(__name__)


def _default_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Build headers for Wellington API. Origin is required; Authorization when token is provided."""
    headers: Dict[str, str] = {"Origin": ORIGIN}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class WellingtonAPIError(Exception):
    """Raised when a Wellington API request fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


async def get_access_token() -> str:
    """
    POST /auth/login and return access_token.
    Uses WELLINGTON_USERNAME, WELLINGTON_PASSWORD, WELLINGTON_CUSTOMER_ID from settings.
    """
    s = get_settings()
    base = s.WELLINGTON_API_BASE_URL.rstrip("/")
    url = f"{base}/auth/login"
    payload = {
        "username": s.WELLINGTON_USERNAME,
        "password": s.WELLINGTON_PASSWORD,
        "remember_me": "yes",
        "company_id": str(s.WELLINGTON_CUSTOMER_ID).strip() or "15",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            json=payload,
            headers=_default_headers(),
        )
        # API may return 200 OK or 201 Created on success
        if resp.status_code not in (200, 201):
            raise WellingtonAPIError(
                f"Login failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise WellingtonAPIError("Login response missing access_token", body=data)
        return token


async def get_schedule(
    date_str: str,
    customer_id: str,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    GET /schedule?date={date}&customer_id={customer_id}.
    date_str: YYYY-MM-DD (interpreted as UTC date).
    Returns dict with 'show' and 'rings' (and optionally show_date, etc.).
    If token is not provided, logs in to obtain one.
    """
    if token is None:
        token = await get_access_token()
    s = get_settings()
    base = s.WELLINGTON_API_BASE_URL.rstrip("/")
    url = f"{base}/schedule"
    params = {"date": date_str, "customer_id": customer_id}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params=params,
            headers=_default_headers(token),
        )
        if resp.status_code != 200:
            raise WellingtonAPIError(
                f"Get schedule failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json()


async def get_entries_my(
    show_id: int,
    customer_id: str,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    GET /entries/my?show_id={show_id}&customer_id={customer_id}.
    Returns dict with 'entries' list and 'total_entries'.
    If token is not provided, logs in to obtain one.
    """
    if token is None:
        token = await get_access_token()
    s = get_settings()
    base = s.WELLINGTON_API_BASE_URL.rstrip("/")
    url = f"{base}/entries/my"
    params = {"show_id": show_id, "customer_id": customer_id}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params=params,
            headers=_default_headers(token),
        )
        if resp.status_code != 200:
            raise WellingtonAPIError(
                f"Get entries/my failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json()


async def get_class(
    class_id: int,
    show_id: int,
    customer_id: str,
    token: Optional[str] = None,
    class_group_id: Optional[int] = None,
) -> dict[str, Any]:
    """
    GET /classes/{class_id}?show_id={show_id}&customer_id={customer_id}&cgid={class_group_id}.
    Returns dict with 'class', 'class_related_data', 'trips' (and optionally cdm_data, jumper_table_info).
    Used by Flow 2 (Class Monitoring). If token is not provided, logs in to obtain one.
    """
    if token is None:
        token = await get_access_token()
    s = get_settings()
    base = s.WELLINGTON_API_BASE_URL.rstrip("/")
    url = f"{base}/classes/{class_id}"
    params: Dict[str, Any] = {
        "show_id": show_id,
        "customer_id": customer_id,
    }
    if class_group_id is not None:
        params["cgid"] = class_group_id
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params=params,
            headers=_default_headers(token),
        )
        if resp.status_code != 200:
            raise WellingtonAPIError(
                f"Get class failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json()


async def get_entry_detail(
    entry_id: int,
    show_id: int,
    customer_id: str,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    GET /entries/{entry_id}?eid={entry_id}&show_id={show_id}&customer_id={customer_id}.
    Returns dict with 'entry', 'classes', 'entry_riders'.
    If token is not provided, logs in to obtain one.
    """
    if token is None:
        token = await get_access_token()
    s = get_settings()
    base = s.WELLINGTON_API_BASE_URL.rstrip("/")
    url = f"{base}/entries/{entry_id}"
    params = {"eid": entry_id, "show_id": show_id, "customer_id": customer_id}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params=params,
            headers=_default_headers(token),
        )
        if resp.status_code != 200:
            raise WellingtonAPIError(
                f"Get entry detail failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json()
