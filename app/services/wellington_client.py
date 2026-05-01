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
    Falls back to WELLINGTON_TOKEN_FALLBACK_URL if direct login doesn't return a token.
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
        if resp.status_code in (200, 201):
            token = resp.json().get("access_token")
            if token:
                return token

        # Direct login failed or returned no token — try fallback
        fallback_url = s.WELLINGTON_TOKEN_FALLBACK_URL.strip()
        if fallback_url:
            logger.warning("Wellington direct login did not return access_token, trying fallback URL")
            fallback_resp = await client.get(fallback_url, timeout=30.0)
            if fallback_resp.status_code == 200:
                token = fallback_resp.json().get("access_token")
                if token:
                    return token
            raise WellingtonAPIError(
                f"Fallback login failed: {fallback_resp.status_code}",
                status_code=fallback_resp.status_code,
                body=fallback_resp.text,
            )

        raise WellingtonAPIError(
            "Login response missing access_token and no fallback configured",
            status_code=resp.status_code,
            body=resp.text,
        )


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


async def get_all_entries(
    show_id: int,
    customer_id: str,
    token: Optional[str] = None,
    page: int = 1,
) -> dict[str, Any]:
    """
    GET /entries?sort_on=number&sort_type=asc&page={page}&show_id={show_id}&customer_id={customer_id}.
    Returns dict with 'entries' list, 'total_entries', 'records_per_page', 'page', 'show_name'.
    Used by the all-show-entries sync (once daily). If token is not provided, logs in to obtain one.
    """
    if token is None:
        token = await get_access_token()
    s = get_settings()
    base = s.WELLINGTON_API_BASE_URL.rstrip("/")
    url = f"{base}/entries"
    params: Dict[str, Any] = {
        "sort_on": "number",
        "sort_type": "asc",
        "page": page,
        "show_id": show_id,
        "customer_id": customer_id,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params=params,
            headers=_default_headers(token),
        )
        if resp.status_code != 200:
            raise WellingtonAPIError(
                f"Get all entries failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json()


async def get_all_entries_all_pages(
    show_id: int,
    customer_id: str,
    token: Optional[str] = None,
    batch_size: int = 10,
) -> tuple[list[dict], int]:
    """
    Fetch ALL pages from GET /entries and return the combined entry list.

    Fetches page 1 to discover total_entries / records_per_page, then fetches
    remaining pages in parallel batches of ``batch_size``.

    Returns (all_entry_dicts, total_count).
    """
    import asyncio  # noqa: PLC0415
    import math  # noqa: PLC0415

    if token is None:
        token = await get_access_token()

    first_page = await get_all_entries(show_id, customer_id, token=token, page=1)
    all_entries: list[dict] = list(first_page.get("entries") or [])
    total = first_page.get("total_entries") or 0
    per_page = first_page.get("records_per_page") or 10
    total_pages = math.ceil(total / per_page) if per_page > 0 else 1

    if total_pages <= 1:
        return all_entries, total

    remaining_pages = list(range(2, total_pages + 1))
    for i in range(0, len(remaining_pages), batch_size):
        batch = remaining_pages[i : i + batch_size]
        tasks = [
            get_all_entries(show_id, customer_id, token=token, page=p)
            for p in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("get_all_entries page failed: %s", r)
                continue
            all_entries.extend(r.get("entries") or [])

    return all_entries, total


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
