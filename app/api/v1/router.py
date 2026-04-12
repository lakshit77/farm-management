"""API v1 router aggregating all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints import chat, entries, hello, push, schedule

api_router = APIRouter()

api_router.include_router(hello.router, prefix="/hello", tags=["hello"])
api_router.include_router(schedule.router)
api_router.include_router(entries.router)
api_router.include_router(chat.router)
api_router.include_router(push.router)
