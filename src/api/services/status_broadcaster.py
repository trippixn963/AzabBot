"""
AzabBot - Bot Status Broadcaster
=================================

Background service that broadcasts bot status to WebSocket clients.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

import psutil

from src.core.logger import logger
from src.utils.async_utils import create_safe_task
from src.api.services.websocket import get_ws_manager

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

STATUS_BROADCAST_INTERVAL = 5  # seconds
TIMEZONE = ZoneInfo("America/New_York")


# =============================================================================
# Status Broadcaster
# =============================================================================

class StatusBroadcaster:
    """
    Background service that broadcasts bot status to WebSocket clients.

    Features:
    - Periodic status broadcasts (every 5 seconds, only when clients connected)
    - Real-time log streaming to WebSocket
    - Command execution notifications
    """

    def __init__(self, bot: "AzabBot") -> None:
        self._bot = bot
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._ws_manager = get_ws_manager()

    async def start(self) -> None:
        """Start the status broadcaster."""
        if self._running:
            return

        self._running = True

        # Register directly with logger for WebSocket streaming
        logger.on_log(self._on_log)

        # Start background task
        self._task = create_safe_task(self._broadcast_loop(), "Status Broadcaster")

        logger.tree("Status Broadcaster Started", [
            ("Interval", f"{STATUS_BROADCAST_INTERVAL}s"),
        ], emoji="📡")

    async def stop(self) -> None:
        """Stop the status broadcaster."""
        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.tree("Status Broadcaster Stopped", [], emoji="📡")

    async def _broadcast_loop(self) -> None:
        """Main loop that broadcasts status periodically."""
        while self._running:
            try:
                await asyncio.sleep(STATUS_BROADCAST_INTERVAL)

                # Only broadcast if there are connected clients
                if self._ws_manager.connection_count > 0:
                    await self._broadcast_status()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Status Broadcast Error", [
                    ("Error", str(e)[:100]),
                ])

    async def _broadcast_status(self) -> None:
        """Broadcast current bot status."""
        if not self._bot.is_ready():
            return

        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        memory_used_mb = memory.used / (1024 * 1024)

        status_data = {
            "online": True,
            "latency_ms": int(self._bot.latency * 1000),
            "cpu_percent": round(cpu_percent, 1),
            "memory_used_mb": round(memory_used_mb, 1),
        }

        await self._ws_manager.broadcast_bot_status(status_data)

    def _on_log(
        self,
        level: str,
        message: str,
        module: str,
        formatted: Optional[str] = None,
    ) -> None:
        """Callback from logger - streams logs to WebSocket."""
        # Only stream if there are connected clients
        if self._ws_manager.connection_count == 0:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._broadcast_log(level, message, module, formatted))
        except RuntimeError:
            pass  # No event loop

    async def _broadcast_log(
        self,
        level: str,
        message: str,
        module: str,
        formatted: Optional[str] = None,
    ) -> None:
        """Broadcast a log entry to WebSocket clients."""
        log_data = {
            "timestamp": datetime.now(TIMEZONE).replace(tzinfo=None).isoformat() + "Z",
            "level": level,
            "message": message,
            "module": module,
        }
        if formatted:
            log_data["formatted"] = formatted
        await self._ws_manager.broadcast_bot_log(log_data)

    async def broadcast_command(
        self,
        command: str,
        user_id: int,
        moderator_id: int,
    ) -> None:
        """Broadcast a command execution event."""
        command_data = {
            "command": command,
            "user_id": str(user_id),
            "moderator_id": str(moderator_id),
            "timestamp": time.time(),
        }
        await self._ws_manager.broadcast_command_executed(command_data)


# =============================================================================
# Singleton
# =============================================================================

_broadcaster: Optional[StatusBroadcaster] = None


def get_status_broadcaster(bot: Optional["AzabBot"] = None) -> Optional[StatusBroadcaster]:
    """Get or create the status broadcaster singleton."""
    global _broadcaster
    if _broadcaster is None and bot is not None:
        _broadcaster = StatusBroadcaster(bot)
    return _broadcaster


def init_status_broadcaster(bot: "AzabBot") -> StatusBroadcaster:
    """Initialize the status broadcaster with the bot instance."""
    global _broadcaster
    _broadcaster = StatusBroadcaster(bot)
    return _broadcaster


__all__ = ["StatusBroadcaster", "get_status_broadcaster", "init_status_broadcaster"]
