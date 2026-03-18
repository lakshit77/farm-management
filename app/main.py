"""Application entry point and FastAPI app factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.v1.router import api_router
from app.core.api_key_middleware import ApiKeyMiddleware
from app.core.config import get_settings
from app.core.logging_config import setup_logging

logger = logging.getLogger(__name__)


def _upsert_stream_bots() -> None:
    """Create / update the three bot users in Stream Chat on startup.

    This is a no-op when STREAM_API_KEY is not configured so the app starts
    cleanly in environments that have not yet set up Stream.
    """
    settings = get_settings()
    if not settings.STREAM_API_KEY or not settings.STREAM_API_SECRET:
        logger.info("Stream Chat not configured — skipping bot upsert")
        return

    try:
        from app.core.stream_client import get_stream_client

        client = get_stream_client()
        client.upsert_users([
            {"id": settings.STREAM_ALLTEAM_BOT_ID, "name": "Team Assistant", "role": "admin"},
            {"id": settings.STREAM_ADMIN_BOT_ID, "name": "Admin Assistant", "role": "admin"},
            {"id": settings.STREAM_PERSONAL_BOT_ID, "name": "Personal Assistant", "role": "admin"},
        ])
        logger.info("Stream Chat bot users upserted successfully")
    except Exception as exc:
        logger.warning("Failed to upsert Stream Chat bot users: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events (startup/shutdown)."""
    # Startup: configure logging (app.log + schedule_daily.log)
    setup_logging()
    # Startup: ensure Stream Chat bot users exist
    _upsert_stream_bots()
    yield
    # Shutdown


app = FastAPI(
    title="Showground Live Monitoring API",
    version="1.0.0",
    description="Horse farm show monitoring and Telegram notifications.",
    lifespan=lifespan,
)

# CORS: with allow_credentials=True, origins cannot be "*". Use explicit list.
# Include common Vite dev server ports (5173–5179) so frontend works regardless of port.
_default_cors_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
    "http://localhost:5177",
    "http://localhost:5178",
    "http://localhost:5179",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
    "http://127.0.0.1:5176",
    "http://127.0.0.1:5177",
    "http://127.0.0.1:5178",
    "http://127.0.0.1:5179",
]


def _get_cors_origins() -> list[str]:
    """Return list of allowed CORS origins from settings or default dev list."""
    settings = get_settings()
    if settings.CORS_ORIGINS.strip():
        return [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    return _default_cors_origins


# Middleware order matters: Starlette applies middleware LIFO (last added = outermost = runs first).
# ApiKeyMiddleware must be added FIRST so CORSMiddleware is outermost and always attaches
# Access-Control-Allow-Origin headers -- even on 401 responses from ApiKeyMiddleware.
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


def custom_openapi() -> dict:
    """Add Bearer auth to OpenAPI so Swagger UI shows the Authorize button."""
    if app.openapi_schema is not None:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = openapi_schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Bearer",
        "description": "API key (API_SECRET_KEY). Enter the token only; Swagger will add 'Bearer '.",
    }
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
