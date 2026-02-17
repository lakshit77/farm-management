"""API v1 router aggregating all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints import hello, schedule

api_router = APIRouter()

api_router.include_router(hello.router, prefix="/hello", tags=["hello"])
api_router.include_router(schedule.router)
