"""
Azab Discord Bot - Health Check Server
=======================================

HTTP health check endpoint for external monitoring.

DESIGN:
    Provides a lightweight HTTP server that external monitoring tools
    (like uptime checkers or orchestration systems) can ping to verify
    the bot is running and responsive.

    The /health endpoint returns JSON with bot status, connection state,
    and basic metrics without exposing sensitive information.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from aiohttp import web
from datetime import datetime
from typing import TYPE_CHECKING

from src.core.logger import logger
from src.core.config import NY_TZ

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Health Check Server
# =============================================================================

class HealthCheckServer:
    """
    Simple HTTP health check server for monitoring.

    DESIGN:
        Uses aiohttp for async HTTP serving within the bot's event loop.
        Binds to 0.0.0.0 to accept external connections.
        Returns JSON responses for easy parsing by monitoring tools.

    Attributes:
        bot: Reference to the main bot instance.
        port: Port number for the HTTP server.
        app: aiohttp Application instance.
        runner: aiohttp AppRunner for lifecycle management.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot", port: int = 8080) -> None:
        """
        Initialize the health check server.

        Args:
            bot: Main bot instance for status queries.
            port: Port to listen on (default 8080).
        """
        self.bot = bot
        self.port = port
        self.app = web.Application()
        self.runner: web.AppRunner = None

        # Setup routes
        self.app.router.add_get("/health", self.health_handler)
        self.app.router.add_get("/", self.health_handler)

    # =========================================================================
    # Request Handlers
    # =========================================================================

    async def health_handler(self, request: web.Request) -> web.Response:
        """
        Handle health check requests.

        DESIGN:
            Returns comprehensive status without sensitive data.
            "healthy" status indicates bot is connected to Discord.
            "starting" status indicates bot is still initializing.

        Args:
            request: Incoming HTTP request.

        Returns:
            JSON response with bot status.
        """
        try:
            is_connected = self.bot.is_ready() if hasattr(self.bot, 'is_ready') else False
            guild_count = len(self.bot.guilds) if hasattr(self.bot, 'guilds') else 0

            status = {
                "status": "healthy" if is_connected else "starting",
                "bot": "Azab",
                "connected": is_connected,
                "guilds": guild_count,
                "disabled": self.bot.disabled,
                "timestamp": datetime.now(NY_TZ).isoformat(),
            }

            logger.debug(f"Health check: {status['status']}")

            return web.json_response(status)

        except Exception as e:
            logger.error("Health Check Error", [
                ("Error", str(e)[:100]),
            ])
            return web.json_response(
                {"status": "error", "error": str(e)},
                status=500,
            )

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start(self) -> None:
        """
        Start the health check server.

        DESIGN:
            Non-blocking startup using aiohttp's AppRunner.
            Binds to all interfaces (0.0.0.0) for external access.
            Logs success with tree format for visibility.
        """
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            site = web.TCPSite(self.runner, "0.0.0.0", self.port)
            await site.start()

            logger.tree("Health Server Started", [
                ("Port", str(self.port)),
                ("Endpoint", f"http://0.0.0.0:{self.port}/health"),
            ], emoji="🏥")

        except Exception as e:
            logger.error("Health Server Startup Failed", [
                ("Port", str(self.port)),
                ("Error", str(e)[:100]),
            ])

    async def stop(self) -> None:
        """
        Stop the health check server gracefully.

        DESIGN:
            Cleans up runner resources on shutdown.
            Safe to call even if server never started.
        """
        if self.runner:
            await self.runner.cleanup()
            logger.info("Health check server stopped")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["HealthCheckServer"]
