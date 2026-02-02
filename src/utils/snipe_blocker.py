"""
AzabBot - Snipe Blocker Utility
===============================

Tracks messages that were auto-deleted by the bot to prevent them
from being saved to the snipe cache.

Used by: content moderation, antispam, external invite deletion, etc.

Author: John Hamwi
Server: discord.gg/syria
"""

import asyncio
from typing import Dict, Optional, Tuple

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

_MAX_TRACKED_IDS = 1000
"""Maximum number of message IDs to track before cleanup."""


# =============================================================================
# Module State
# =============================================================================

# Maps message_id -> (reason, user_id, channel_name)
_blocked_messages: Dict[int, Tuple[str, Optional[int], Optional[str]]] = {}
_lock = asyncio.Lock()


# =============================================================================
# Public API
# =============================================================================

async def block_from_snipe(
    message_id: int,
    reason: str = "Bot auto-delete",
    user_id: Optional[int] = None,
    channel_name: Optional[str] = None,
) -> None:
    """
    Mark a message to be blocked from snipe cache.

    Call this BEFORE deleting a message to prevent it from being
    saved to the snipe cache when the on_message_delete event fires.

    Args:
        message_id: The message ID to block from snipe.
        reason: The reason for blocking (e.g., "Religion talk", "Spam").
        user_id: The user ID who sent the message (for logging).
        channel_name: The channel name where the message was (for logging).
    """
    async with _lock:
        _blocked_messages[message_id] = (reason, user_id, channel_name)

        logger.tree("SNIPE BLOCKED", [
            ("Message ID", str(message_id)),
            ("Reason", reason),
            ("User ID", str(user_id) if user_id else "Unknown"),
            ("Channel", channel_name or "Unknown"),
        ], emoji="🚫")

        # Cleanup: prevent unbounded growth
        if len(_blocked_messages) > _MAX_TRACKED_IDS:
            # Remove oldest entries (dict maintains insertion order in Python 3.7+)
            keys_to_remove = list(_blocked_messages.keys())[:_MAX_TRACKED_IDS // 2]
            for msg_id in keys_to_remove:
                _blocked_messages.pop(msg_id, None)
            logger.tree("Snipe Blocker Cleanup", [
                ("Removed", str(len(keys_to_remove))),
                ("Remaining", str(len(_blocked_messages))),
            ], emoji="🧹")


async def should_block_snipe(message_id: int) -> Tuple[bool, Optional[str]]:
    """
    Check if a message should be blocked from snipe cache.

    This removes the ID from tracking after checking (one-time use).

    Args:
        message_id: The message ID to check.

    Returns:
        Tuple of (should_block, reason). If should_block is False, reason is None.
    """
    async with _lock:
        if message_id in _blocked_messages:
            reason, user_id, channel_name = _blocked_messages.pop(message_id)
            return True, reason
        return False, None


__all__ = ["block_from_snipe", "should_block_snipe"]
