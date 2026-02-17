"""Simple hello-world endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/", response_model=dict[str, str])
async def hello() -> dict[str, str]:
    """Return a simple greeting."""
    return {"message": "Hello, world!"}
