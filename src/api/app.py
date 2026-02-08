"""
AzabBot - FastAPI Application
=============================

FastAPI application factory and configuration.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from src.core.logger import logger
from src.api.config import get_api_config
from src.api.middleware.rate_limit import RateLimitMiddleware, get_rate_limiter
from src.api.middleware.logging import LoggingMiddleware
from src.api.services.websocket import get_ws_manager
from src.api.services.event_storage import get_event_storage
from src.api.dependencies import set_bot
from src.api.routers import (
    health_router,
    auth_router,
    cases_router,
    tickets_router,
    transcripts_router,
    case_transcripts_router,
    appeals_router,
    appeal_form_router,
    users_router,
    stats_router,
    websocket_router,
    server_router,
    dashboard_router,
    bans_router,
    frontend_logs_router,
    bot_router,
    events_router,
)


# =============================================================================
# Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Handles startup and shutdown events.
    """
    # Startup
    logger.tree("API Starting", [
        ("Version", "1.0.0"),
    ], emoji="🚀")

    # Start WebSocket heartbeat
    ws_manager = get_ws_manager()
    await ws_manager.start_heartbeat()

    # Wire up event storage to WebSocket for real-time updates
    event_storage = get_event_storage()

    def broadcast_event(event_data: dict):
        """Callback to broadcast events via WebSocket."""
        from src.utils.async_utils import create_safe_task
        try:
            create_safe_task(
                ws_manager.broadcast_discord_event(event_data),
                "WS Event Broadcast"
            )
        except RuntimeError:
            pass  # No event loop running

    event_storage.set_on_event(broadcast_event)

    yield

    # Shutdown
    logger.tree("API Stopping", [], emoji="🛑")

    # Stop WebSocket heartbeat
    await ws_manager.stop_heartbeat()


# =============================================================================
# Application Factory
# =============================================================================

def create_app(bot: Optional[Any] = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        bot: Optional Discord bot instance for dependency injection

    Returns:
        Configured FastAPI application
    """
    config = get_api_config()

    # Create app
    app = FastAPI(
        title="AzabBot API",
        description="Moderation dashboard API for AzabBot",
        version="1.0.0",
        docs_url="/api/azab/docs" if config.debug else None,
        redoc_url="/api/azab/redoc" if config.debug else None,
        openapi_url="/api/azab/openapi.json" if config.debug else None,
        lifespan=lifespan,
    )

    # Set bot reference
    if bot:
        set_bot(bot)

    # ==========================================================================
    # Middleware (order matters - last added = first executed)
    # ==========================================================================

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.add_middleware(RateLimitMiddleware, rate_limiter=get_rate_limiter())

    # Request logging
    app.add_middleware(LoggingMiddleware)

    # ==========================================================================
    # Exception Handlers
    # ==========================================================================

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle uncaught exceptions."""
        logger.error("Unhandled API Error", [
            ("Path", str(request.url.path)[:50]),
            ("Error", str(exc)[:100]),
        ])

        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "Internal server error",
                "data": None,
            },
        )

    # ==========================================================================
    # Routers
    # ==========================================================================

    app.include_router(health_router, prefix="/api/azab")
    app.include_router(auth_router, prefix="/api/azab")
    app.include_router(server_router, prefix="/api/azab")
    app.include_router(dashboard_router, prefix="/api/azab")
    app.include_router(cases_router, prefix="/api/azab")
    app.include_router(tickets_router, prefix="/api/azab")
    app.include_router(transcripts_router, prefix="/api/azab")
    app.include_router(case_transcripts_router, prefix="/api/azab")
    app.include_router(appeals_router, prefix="/api/azab")
    app.include_router(appeal_form_router, prefix="/api/azab")
    app.include_router(users_router, prefix="/api/azab")
    app.include_router(stats_router, prefix="/api/azab")
    app.include_router(bans_router, prefix="/api/azab")
    app.include_router(frontend_logs_router, prefix="/api/azab")
    app.include_router(bot_router, prefix="/api/azab")
    app.include_router(events_router, prefix="/api/azab")
    app.include_router(websocket_router, prefix="/api/azab")

    # Root health check (for load balancers)
    @app.get("/health")
    async def root_health():
        return {"status": "healthy"}

    return app


# =============================================================================
# Module-level app for uvicorn
# =============================================================================

# This allows running with: uvicorn src.api.app:app
app = create_app()


__all__ = ["create_app", "app"]
