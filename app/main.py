"""Application entry point and FastAPI app factory."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.logging_config import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events (startup/shutdown)."""
    # Startup: configure logging (app.log + schedule_daily.log)
    setup_logging()
    yield
    # Shutdown


app = FastAPI(
    title="Showground Live Monitoring API",
    version="1.0.0",
    description="Horse farm show monitoring and Telegram notifications.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
