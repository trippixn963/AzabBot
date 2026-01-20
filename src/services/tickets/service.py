"""
Azab Discord Bot - Ticket Service
==================================

Core service logic for the ticket system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict

import discord

from src.core.logger import logger
from src.core.config import get_config
from src.core.database import get_db
from src.core.constants import (
    TICKET_CREATION_COOLDOWN,
    AUTO_CLOSE_CHECK_INTERVAL,
    THREAD_DELETE_DELAY,
    CLOSE_REQUEST_COOLDOWN,
)
from src.utils.async_utils import create_safe_task

from .constants import (
    INACTIVE_WARNING_DAYS,
    INACTIVE_CLOSE_DAYS,
    DELETE_AFTER_CLOSE_DAYS,
)

# Import mixins
from .auto_close import AutoCloseMixin
from .ticket_helpers import HelpersMixin
from .operations import OperationsMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class TicketService(AutoCloseMixin, HelpersMixin, OperationsMixin):
    """
    Service for managing support tickets.

    DESIGN:
        Tickets are created as threads in a dedicated text channel.
        Each ticket gets its own thread with sequential ID (T001, T002, etc.).
        All operations via buttons - no slash commands.

        Single Control Panel Pattern:
        - One embed per ticket that updates in place
        - Buttons change based on ticket status
        - Simple notification messages (no buttons) for actions
    """

    THREAD_CACHE_TTL = timedelta(minutes=5)

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._channel: Optional[discord.TextChannel] = None
        self._channel_cache_time: Optional[datetime] = None
        self._thread_cache: Dict[int, tuple[discord.Thread, datetime]] = {}
        self._auto_close_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._creation_cooldowns: Dict[int, float] = {}
        self._close_request_cooldowns: Dict[str, float] = {}
        self._pending_deletions: Dict[str, asyncio.Task] = {}
        self._cache_lookup_count: int = 0  # Counter for periodic cache cleanup
        # Locks for thread-safe dict access
        self._cooldowns_lock = asyncio.Lock()
        self._deletions_lock = asyncio.Lock()

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if ticket system is enabled."""
        return self.config.ticket_channel_id is not None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the ticket service and auto-close scheduler."""
        if not self.enabled:
            logger.info("Ticket service disabled (no channel configured)")
            return

        self._running = True
        self._auto_close_task = create_safe_task(
            self._auto_close_loop(), "Ticket Auto-Close Loop"
        )
        logger.tree("Ticket Service Started", [
            ("Auto-close", f"Enabled (warn: {INACTIVE_WARNING_DAYS}d, close: {INACTIVE_CLOSE_DAYS}d)"),
            ("Auto-delete", f"Enabled ({DELETE_AFTER_CLOSE_DAYS}d after close)"),
            ("Check interval", f"{AUTO_CLOSE_CHECK_INTERVAL}s"),
        ], emoji="🎫")

    async def stop(self) -> None:
        """Stop the ticket service and cleanup."""
        self._running = False
        if self._auto_close_task and not self._auto_close_task.done():
            self._auto_close_task.cancel()
            try:
                await self._auto_close_task
            except asyncio.CancelledError:
                pass

        # Cancel pending deletions
        async with self._deletions_lock:
            for task in self._pending_deletions.values():
                if not task.done():
                    task.cancel()
            self._pending_deletions.clear()

        logger.debug("Ticket Service Stopped")

    # =========================================================================
    # Activity Tracking
    # =========================================================================

    async def track_ticket_activity(self, thread_id: int) -> None:
        """Track activity in a ticket thread."""
        ticket = self.db.get_ticket_by_thread(thread_id)
        if not ticket:
            return

        if ticket["status"] == "closed":
            return

        self.db.update_ticket_activity(ticket["ticket_id"])

        # Clear warning flag if ticket becomes active again
        if ticket.get("warned"):
            self.db.clear_ticket_warning(ticket["ticket_id"])
