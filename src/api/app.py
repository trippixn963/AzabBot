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
from src.api.errors import ErrorCode, error_response
from src.api.middleware.rate_limit import RateLimitMiddleware, get_rate_limiter
from src.api.middleware.logging import LoggingMiddleware
from src.api.services.websocket import get_ws_manager
from src.api.services.event_storage import get_event_storage
from src.api.dependencies import set_bot


# =============================================================================
# OpenAPI Documentation
# =============================================================================

API_DESCRIPTION = """
## AzabBot Moderation Dashboard API

Backend API for the AzabBot moderation dashboard, providing real-time access to
moderation cases, tickets, appeals, and server statistics.

### Authentication

All endpoints (except `/health` and public appeal forms) require JWT authentication.

**Getting a Token:**
1. Authenticate via Discord OAuth at `/api/azab/auth/discord`
2. Use the returned access token in the `Authorization` header

**Token Format:**
```
Authorization: Bearer <access_token>
```

### Rate Limits

| Endpoint Type | Limit | Window |
|--------------|-------|--------|
| Default | 60 requests | 1 minute |
| Auth endpoints | 5 requests | 1 minute |
| Stats endpoints | 120 requests | 1 minute |

Rate limit headers are included in all responses:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining
- `Retry-After`: Seconds to wait (on 429)

### WebSocket

Real-time updates are available via WebSocket at `/api/azab/ws`.

**Events:**
- `case.created`, `case.updated`, `case.resolved`
- `ticket.created`, `ticket.claimed`, `ticket.closed`
- `appeal.submitted`, `appeal.approved`, `appeal.denied`
- `stats.updated`, `bot_status`

### Error Responses

All errors follow a consistent format:
```json
{
    "success": false,
    "error_code": "CASE_NOT_FOUND",
    "message": "Moderation case not found",
    "details": null
}
```

See the error code reference for all possible codes.
"""

OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": "Health check and status endpoints",
    },
    {
        "name": "Auth",
        "description": "Authentication and authorization via Discord OAuth",
    },
    {
        "name": "Dashboard",
        "description": "Dashboard overview and summary statistics",
    },
    {
        "name": "Cases",
        "description": "Moderation case management (mutes, bans, warns, etc.)",
    },
    {
        "name": "Tickets",
        "description": "Support ticket system",
    },
    {
        "name": "Appeals",
        "description": "Punishment appeal management",
    },
    {
        "name": "Users",
        "description": "User lookup and moderation history",
    },
    {
        "name": "Bans",
        "description": "Server ban management",
    },
    {
        "name": "Stats",
        "description": "Moderation statistics and analytics",
    },
    {
        "name": "Server",
        "description": "Server configuration and info",
    },
    {
        "name": "Bot",
        "description": "Bot status and management",
    },
    {
        "name": "Events",
        "description": "Discord event stream",
    },
    {
        "name": "WebSocket",
        "description": "Real-time WebSocket connections",
    },
    {
        "name": "Transcripts",
        "description": "Case and ticket transcript access",
    },
    {
        "name": "Logs",
        "description": "Frontend logging endpoints",
    },
]
from src.api.routers import (
    health_router,
    auth_router,
    cases_router,
    tickets_router,
    ticket_transcripts_router,
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
        ("Version", "2.0.0"),
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

    # Create app with enhanced OpenAPI documentation
    app = FastAPI(
        title="AzabBot API",
        description=API_DESCRIPTION,
        version="2.0.0",
        docs_url="/api/azab/docs" if config.debug else None,
        redoc_url="/api/azab/redoc" if config.debug else None,
        openapi_url="/api/azab/openapi.json" if config.debug else None,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        license_info={
            "name": "Private",
            "url": "https://discord.gg/syria",
        },
        contact={
            "name": "AzabBot Support",
            "url": "https://discord.gg/syria",
        },
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
        """Handle uncaught exceptions with consistent error format."""
        logger.error("Unhandled API Error", [
            ("Path", str(request.url.path)[:50]),
            ("Method", request.method),
            ("Error Type", type(exc).__name__),
            ("Error", str(exc)[:100]),
        ])

        return error_response(
            ErrorCode.SERVER_ERROR,
            details={"path": str(request.url.path)} if config.debug else None,
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
    app.include_router(ticket_transcripts_router, prefix="/api/azab")
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
