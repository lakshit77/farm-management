"""Global API response schema used by all endpoints."""

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

from app.core.enums import ApiResponseMessage

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    Standard API response envelope for all endpoints.

    - status: 1 for success, 0 for error.
    - message: "success" when status=1, or error description when status=0.
    - data: optional payload; omit or null when no data to return.
    """

    status: int  # 1 = success, 0 = error
    message: str
    data: Optional[T] = None


def success_response(
    data: Any = None, message: str = ApiResponseMessage.SUCCESS.value
) -> ApiResponse[Any]:
    """Build a successful API response (status=1)."""
    return ApiResponse(status=1, message=message, data=data)


def error_response(message: str, data: Any = None) -> ApiResponse[Any]:
    """Build an error API response (status=0)."""
    return ApiResponse(status=0, message=message, data=data)
