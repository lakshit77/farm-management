"""Middleware to enforce Bearer API key for all paths except /api/v1/hello."""

import json
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings

# Paths that do not require the API key (exact match after normalizing trailing slash)
# EXEMPT_PATHS = {"/api/v1/hello", "/api/v1/hello/"}
EXEMPT_PATHS = {"/docs", "/openapi.json"}

# 401 response body: status=0, message as per project API response format
UNAUTHORIZED_MESSAGE = "Invalid or missing API key."
UNAUTHORIZED_BODY = json.dumps({"status": 0, "message": UNAUTHORIZED_MESSAGE}).encode()


def _path_exempt(path: str) -> bool:
    """Return True if the request path is exempt from API key check."""
    return path in EXEMPT_PATHS


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """
    Require Authorization: Bearer <API_SECRET_KEY> for all requests
    except those to /api/v1/hello (and /api/v1/hello/).
    If API_SECRET_KEY is not set, no check is performed.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.scope.get("path", "")
        if _path_exempt(path):
            return await call_next(request)

        settings = get_settings()
        if not settings.API_SECRET_KEY:
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            return Response(
                content=UNAUTHORIZED_BODY,
                status_code=401,
                media_type="application/json",
            )
        token = auth[7:].strip()
        # Constant-time compare to reduce timing side-channel risk
        if not _secure_compare(token, settings.API_SECRET_KEY):
            return Response(
                content=UNAUTHORIZED_BODY,
                status_code=401,
                media_type="application/json",
            )
        return await call_next(request)


def _secure_compare(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0
