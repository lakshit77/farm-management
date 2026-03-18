"""Stream Chat server-side client singleton.

Initialised once from settings and cached via lru_cache so the same
StreamChat instance is reused across all requests.

Uses the official `stream-chat` Python SDK (pip install stream-chat).
"""

from functools import lru_cache

from stream_chat import StreamChat

from app.core.config import get_settings


@lru_cache
def get_stream_client() -> StreamChat:
    """Return a cached Stream Chat server client."""
    settings = get_settings()
    return StreamChat(
        api_key=settings.STREAM_API_KEY,
        api_secret=settings.STREAM_API_SECRET,
    )
