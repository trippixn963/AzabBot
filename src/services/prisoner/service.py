"""
AzabBot - Prisoner Service
==========================

Centralized service for prisoner message tracking, cooldowns, and response batching.

Extracted from bot.py to improve maintainability and separation of concerns.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from src.core.logger import logger
from src.core.config import get_config

if TYPE_CHECKING:
    from src.bot import AzabBot

# =============================================================================
# Constants
# =============================================================================

# Max prisoner entries to prevent unbounded memory growth
PRISONER_TRACKING_LIMIT = 1000

# Max messages per prisoner buffer before forcing a response
MESSAGE_BUFFER_LIMIT = 50


# =============================================================================
# Prisoner Service
# =============================================================================

class PrisonerService:
    """
    Service for managing prisoner message tracking and response batching.

    This service handles:
    - Rate limiting responses to prisoners (cooldowns)
    - Batching multiple messages for context-aware responses
    - Tracking pending response flags to prevent duplicate responses
    - Cleanup of stale prisoner tracking data

    Thread Safety:
        All operations on internal dictionaries are protected by `_lock`.
        Always use `async with self._lock:` when accessing internal state.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the prisoner service.

        Args:
            bot: The AzabBot instance.
        """
        self.bot = bot
        self.config = get_config()

        # Main lock protecting all internal state
        self._lock = asyncio.Lock()

        # Cooldowns: user_id -> last response time
        self._cooldowns: Dict[int, datetime] = {}

        # Message buffers: user_id -> list of message contents
        self._message_buffers: Dict[int, List[str]] = {}

        # Pending response flags: user_id -> True if response is being generated
        self._pending_responses: Dict[int, bool] = {}

        logger.tree("Prisoner Service Initialized", [
            ("Tracking Limit", str(PRISONER_TRACKING_LIMIT)),
            ("Buffer Limit", str(MESSAGE_BUFFER_LIMIT)),
        ], emoji="🔒")

    # =========================================================================
    # Cooldown Management
    # =========================================================================

    async def get_cooldown(self, user_id: int) -> Optional[datetime]:
        """
        Get the last response time for a user.

        Args:
            user_id: The user's Discord ID.

        Returns:
            The datetime of the last response, or None if not on cooldown.
        """
        async with self._lock:
            return self._cooldowns.get(user_id)

    async def set_cooldown(self, user_id: int, timestamp: Optional[datetime] = None) -> None:
        """
        Set the cooldown timestamp for a user.

        Args:
            user_id: The user's Discord ID.
            timestamp: The cooldown timestamp (defaults to now).
        """
        async with self._lock:
            self._cooldowns[user_id] = timestamp or datetime.now()
            logger.debug("Prisoner Cooldown Set", [("User", str(user_id))])

    async def clear_cooldown(self, user_id: int) -> bool:
        """
        Clear the cooldown for a user.

        Args:
            user_id: The user's Discord ID.

        Returns:
            True if cooldown was cleared, False if user had no cooldown.
        """
        async with self._lock:
            return self._cooldowns.pop(user_id, None) is not None

    # =========================================================================
    # Message Buffer Management
    # =========================================================================

    async def add_to_buffer(self, user_id: int, content: str) -> int:
        """
        Add a message to the user's buffer.

        Args:
            user_id: The user's Discord ID.
            content: The message content to buffer.

        Returns:
            The current buffer size for the user.
        """
        async with self._lock:
            if user_id not in self._message_buffers:
                self._message_buffers[user_id] = []

            # Enforce per-user buffer limit
            if len(self._message_buffers[user_id]) < MESSAGE_BUFFER_LIMIT:
                self._message_buffers[user_id].append(content)

            return len(self._message_buffers[user_id])

    async def get_buffer(self, user_id: int) -> List[str]:
        """
        Get a copy of the user's message buffer.

        Args:
            user_id: The user's Discord ID.

        Returns:
            A copy of the message buffer (empty list if none).
        """
        async with self._lock:
            return list(self._message_buffers.get(user_id, []))

    async def clear_buffer(self, user_id: int) -> List[str]:
        """
        Clear and return the user's message buffer.

        Args:
            user_id: The user's Discord ID.

        Returns:
            The cleared buffer contents.
        """
        async with self._lock:
            buffer = self._message_buffers.pop(user_id, [])
            if buffer:
                logger.debug("Prisoner Buffer Cleared", [("User", str(user_id)), ("Messages", str(len(buffer)))])
            return buffer

    async def get_buffer_size(self, user_id: int) -> int:
        """
        Get the current buffer size for a user.

        Args:
            user_id: The user's Discord ID.

        Returns:
            Number of messages in the buffer.
        """
        async with self._lock:
            return len(self._message_buffers.get(user_id, []))

    # =========================================================================
    # Pending Response Management
    # =========================================================================

    async def is_pending(self, user_id: int) -> bool:
        """
        Check if a response is pending for a user.

        Args:
            user_id: The user's Discord ID.

        Returns:
            True if a response is being generated.
        """
        async with self._lock:
            return self._pending_responses.get(user_id, False)

    async def set_pending(self, user_id: int, pending: bool = True) -> None:
        """
        Set the pending response flag for a user.

        Args:
            user_id: The user's Discord ID.
            pending: Whether a response is pending.
        """
        async with self._lock:
            if pending:
                self._pending_responses[user_id] = True
            else:
                self._pending_responses.pop(user_id, None)

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def cleanup_for_user(self, user_id: int) -> None:
        """
        Remove all tracking data for a user (e.g., when unmuted).

        Args:
            user_id: The user's Discord ID.
        """
        async with self._lock:
            had_data = (
                user_id in self._cooldowns or
                user_id in self._message_buffers or
                user_id in self._pending_responses
            )
            self._cooldowns.pop(user_id, None)
            self._message_buffers.pop(user_id, None)
            self._pending_responses.pop(user_id, None)

            if had_data:
                logger.tree("Prisoner Tracking Cleared", [
                    ("User ID", str(user_id)),
                    ("Reason", "User unmuted or left"),
                ], emoji="🧹")

    async def cleanup_stale_entries(self) -> int:
        """
        Clean up prisoner tracking for users no longer muted.

        Removes entries for users not currently muted in any guild.
        Also enforces maximum tracking limits.

        Returns:
            Number of entries cleaned up.
        """
        if not self.config.muted_role_id:
            return 0

        # Get all currently muted user IDs across all guilds
        muted_user_ids: Set[int] = set()
        for guild in self.bot.guilds:
            for member in guild.members:
                if any(r.id == self.config.muted_role_id for r in member.roles):
                    muted_user_ids.add(member.id)

        cleaned = 0

        async with self._lock:
            # Clean cooldowns
            for user_id in list(self._cooldowns.keys()):
                if user_id not in muted_user_ids:
                    self._cooldowns.pop(user_id, None)
                    cleaned += 1

            # Clean message buffers
            for user_id in list(self._message_buffers.keys()):
                if user_id not in muted_user_ids:
                    self._message_buffers.pop(user_id, None)
                    cleaned += 1

            # Clean pending response flags
            for user_id in list(self._pending_responses.keys()):
                if user_id not in muted_user_ids:
                    self._pending_responses.pop(user_id, None)
                    cleaned += 1

            # Enforce max size limits (evict oldest entries if over limit)
            while len(self._cooldowns) > PRISONER_TRACKING_LIMIT:
                try:
                    oldest_key = next(iter(self._cooldowns))
                    self._cooldowns.pop(oldest_key, None)
                    cleaned += 1
                except StopIteration:
                    break

        if cleaned > 0:
            logger.tree("Prisoner Tracking Cleanup", [
                ("Entries Removed", str(cleaned)),
                ("Remaining Cooldowns", str(len(self._cooldowns))),
                ("Remaining Buffers", str(len(self._message_buffers))),
            ], emoji="🧹")

        return cleaned

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> dict:
        """
        Get current service statistics.

        Returns:
            Dictionary with tracking counts.
        """
        async with self._lock:
            return {
                "cooldowns": len(self._cooldowns),
                "buffers": len(self._message_buffers),
                "pending": sum(1 for v in self._pending_responses.values() if v),
                "total_buffered_messages": sum(
                    len(msgs) for msgs in self._message_buffers.values()
                ),
            }


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["PrisonerService"]
