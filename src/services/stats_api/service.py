"""
AzabBot - Service
=================

Main AzabAPI class with lifecycle methods.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from aiohttp import web

from src.core.config import get_config, NY_TZ
from src.core.logger import logger
from src.core.constants import STATS_API_PORT
from src.utils.async_utils import create_safe_task

from .middleware import (
    ResponseCache,
    rate_limiter,
    rate_limit_middleware,
    security_headers_middleware,
)
from .handlers import HandlersMixin
from .data_helpers import DataHelpersMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

STATS_API_HOST = "0.0.0.0"


# =============================================================================
# AzabAPI Class
# =============================================================================

class AzabAPI(HandlersMixin, DataHelpersMixin):
    """HTTP API server for Azab moderation stats."""

    def __init__(self, bot: "AzabBot") -> None:
        self._bot = bot
        self._config = get_config()
        self._start_time: Optional[datetime] = None
        self._cache = ResponseCache()
        self._cleanup_task: Optional[asyncio.Task] = None
        self.runner: Optional[web.AppRunner] = None
        self.app: Optional[web.Application] = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the API server."""
        self._start_time = datetime.now(NY_TZ)

        # Create app with middleware
        self.app = web.Application(middlewares=[
            rate_limit_middleware,
            security_headers_middleware,
        ])

        # Setup routes
        self._setup_routes()

        # Start server
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(self.runner, STATS_API_HOST, STATS_API_PORT)
        await site.start()

        # Start cleanup task
        self._cleanup_task = create_safe_task(self._cleanup_loop(), "Stats API Cleanup")

        logger.tree("Azab API Started", [
            ("Host", STATS_API_HOST),
            ("Port", str(STATS_API_PORT)),
            ("Endpoints", "/api/azab/stats, /api/azab/user/{id}, /health"),
            ("Rate Limit", "60 req/min, 10 burst"),
        ], emoji="🌐")

    async def stop(self) -> None:
        """Stop the API server."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        if self.runner:
            await self.runner.cleanup()
            self.runner = None

        logger.info("🌐 Azab API Stopped")

    def _setup_routes(self) -> None:
        """Configure API routes."""
        self.app.router.add_get("/api/azab/stats", self.handle_stats)
        self.app.router.add_get("/api/azab/leaderboard", self.handle_leaderboard)
        self.app.router.add_get("/api/azab/user/{user_id}", self.handle_user)
        self.app.router.add_get("/api/azab/moderator/{user_id}", self.handle_moderator)
        self.app.router.add_get("/api/azab/transcripts/{ticket_id}", self.handle_transcript)
        self.app.router.add_get("/health", self.handle_health)

    async def _cleanup_loop(self) -> None:
        """Periodically clean up rate limiter entries."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                await rate_limiter.cleanup()
            except asyncio.CancelledError:
                break
            except Exception:
                pass


__all__ = ["AzabAPI"]
