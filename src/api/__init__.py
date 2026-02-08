"""
AzabBot - API Package
=====================

FastAPI-based REST API for the moderation dashboard.

Author: حَـــــنَّـــــا
Server: discord.gg/syria

Features:
- JWT-based authentication for moderators
- Real-time WebSocket updates for dashboard
- Full CRUD for cases, tickets, and appeals
- Moderator statistics and leaderboards
- Rate limiting and request logging

Usage with bot:
    from src.api import APIService

    # In your bot's setup
    api_service = APIService(bot)
    await api_service.start()

    # On shutdown
    await api_service.stop()

Standalone (for development):
    uvicorn src.api.app:app --reload
"""

import asyncio
from typing import TYPE_CHECKING, Optional

import uvicorn

if TYPE_CHECKING:
    from src.bot import AzabBot

from src.core.logger import logger
from src.utils.async_utils import create_safe_task
from src.api.config import get_api_config, APIConfig
from src.api.app import create_app
from src.api.dependencies import set_bot
from src.api.services.websocket import get_ws_manager, WebSocketManager
from src.api.services.auth import get_auth_service, AuthService
from src.api.services.snapshots import (
    get_snapshot_service,
    init_snapshot_service,
    SnapshotService,
)
from src.api.services.status_broadcaster import (
    get_status_broadcaster,
    init_status_broadcaster,
    StatusBroadcaster,
)
from src.api.services.log_buffer import get_log_buffer, LogBuffer


# =============================================================================
# API Service
# =============================================================================

class APIService:
    """
    Manages the FastAPI server lifecycle within the Discord bot.

    This service runs the API server in a background task, allowing
    the bot and API to run concurrently.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the API service.

        Args:
            bot: The Discord bot instance
        """
        self._bot = bot
        self._config = get_api_config()
        self._app = create_app(bot)
        self._server: Optional[uvicorn.Server] = None
        self._task: Optional[asyncio.Task] = None
        self._snapshot_service = init_snapshot_service(bot)
        self._status_broadcaster = init_status_broadcaster(bot)

    @property
    def is_running(self) -> bool:
        """Check if the API server is running."""
        return self._task is not None and not self._task.done()

    @property
    def ws_manager(self) -> WebSocketManager:
        """Get the WebSocket manager for broadcasting events."""
        return get_ws_manager()

    @property
    def auth_service(self) -> AuthService:
        """Get the auth service."""
        return get_auth_service()

    @property
    def snapshot_service(self) -> SnapshotService:
        """Get the snapshot service."""
        return self._snapshot_service

    @property
    def status_broadcaster(self) -> StatusBroadcaster:
        """Get the status broadcaster."""
        return self._status_broadcaster

    @property
    def log_buffer(self) -> LogBuffer:
        """Get the log buffer."""
        return get_log_buffer()

    async def start(self) -> None:
        """Start the API server in a background task."""
        if self.is_running:
            logger.warning("API Already Running", [])
            return

        # Configure uvicorn
        config = uvicorn.Config(
            app=self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",  # Reduce uvicorn logging
            access_log=False,  # We have our own logging middleware
        )

        self._server = uvicorn.Server(config)

        # Run in background
        self._task = create_safe_task(self._run_server(), "API Server")

        # Start snapshot service
        await self._snapshot_service.start()

        # Start status broadcaster
        await self._status_broadcaster.start()

        logger.tree("API Service Started", [
            ("Host", self._config.host),
            ("Port", str(self._config.port)),
            ("Debug", str(self._config.debug)),
        ], emoji="🌐")

    async def _run_server(self) -> None:
        """Run the uvicorn server."""
        try:
            await self._server.serve()
        except asyncio.CancelledError:
            logger.debug("API Server Cancelled", [])
        except Exception as e:
            logger.error("API Server Error", [
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])

    async def stop(self) -> None:
        """Stop the API server gracefully."""
        if not self.is_running:
            return

        logger.tree("API Service Stopping", [], emoji="🛑")

        # Stop status broadcaster
        await self._status_broadcaster.stop()

        # Stop snapshot service
        await self._snapshot_service.stop()

        # Signal server to stop
        if self._server:
            self._server.should_exit = True

        # Wait for task to complete
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        self._server = None
        self._task = None

        logger.tree("API Service Stopped", [], emoji="✅")

    # =========================================================================
    # Event Broadcasting (convenience methods)
    # =========================================================================

    async def broadcast_case_created(self, case_data: dict) -> int:
        """Broadcast a new case event to WebSocket clients."""
        return await self.ws_manager.broadcast_case_created(case_data)

    async def broadcast_case_updated(self, case_data: dict) -> int:
        """Broadcast a case update event."""
        return await self.ws_manager.broadcast_case_updated(case_data)

    async def broadcast_case_resolved(self, case_data: dict) -> int:
        """Broadcast a case resolved event."""
        return await self.ws_manager.broadcast_case_resolved(case_data)

    async def broadcast_ticket_created(self, ticket_data: dict) -> int:
        """Broadcast a new ticket event."""
        return await self.ws_manager.broadcast_ticket_created(ticket_data)

    async def broadcast_ticket_claimed(self, ticket_data: dict) -> int:
        """Broadcast a ticket claimed event."""
        return await self.ws_manager.broadcast_ticket_claimed(ticket_data)

    async def broadcast_ticket_closed(self, ticket_data: dict) -> int:
        """Broadcast a ticket closed event."""
        return await self.ws_manager.broadcast_ticket_closed(ticket_data)

    async def broadcast_appeal_submitted(self, appeal_data: dict) -> int:
        """Broadcast a new appeal event."""
        return await self.ws_manager.broadcast_appeal_submitted(appeal_data)

    async def broadcast_appeal_resolved(self, appeal_data: dict, approved: bool) -> int:
        """Broadcast an appeal resolution event."""
        return await self.ws_manager.broadcast_appeal_resolved(appeal_data, approved)

    async def broadcast_mod_action(self, action_data: dict) -> int:
        """Broadcast a general moderation action event."""
        return await self.ws_manager.broadcast_mod_action(action_data)

    async def broadcast_stats_updated(self, stats_data: dict = None) -> int:
        """Broadcast a stats update event to trigger dashboard refresh."""
        return await self.ws_manager.broadcast_stats_updated(stats_data)

    async def broadcast_bot_status(self, status_data: dict) -> int:
        """Broadcast bot status update (latency, CPU, memory)."""
        return await self.ws_manager.broadcast_bot_status(status_data)

    async def broadcast_bot_log(self, log_data: dict) -> int:
        """Broadcast a new log entry."""
        return await self.ws_manager.broadcast_bot_log(log_data)

    async def broadcast_command_executed(self, command_data: dict) -> int:
        """Broadcast a command execution event."""
        return await self.ws_manager.broadcast_command_executed(command_data)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Main service
    "APIService",
    # Config
    "get_api_config",
    "APIConfig",
    # App factory
    "create_app",
    # Services
    "get_ws_manager",
    "WebSocketManager",
    "get_auth_service",
    "AuthService",
    "get_snapshot_service",
    "SnapshotService",
    "get_status_broadcaster",
    "StatusBroadcaster",
    "get_log_buffer",
    "LogBuffer",
    # Dependencies
    "set_bot",
]
