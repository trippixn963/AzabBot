"""
Mod Tracker - Cache Mixin
=========================

Message caching and cleanup operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional, Tuple

import aiohttp
import discord

from src.core.logger import logger
from src.core.config import NY_TZ

from .constants import (
    MESSAGE_CACHE_SIZE,
    MESSAGE_CACHE_TTL,
    MESSAGE_CACHE_MAX_MODS,
    ACTION_HISTORY_MAX_ENTRIES,
    BAN_HISTORY_MAX_ENTRIES,
    PERMISSION_CHANGES_MAX,
    TARGET_ACTIONS_MAX_ENTRIES,
)
from .helpers import CachedMessage

if TYPE_CHECKING:
    from .service import ModTrackerService


class CacheMixin:
    """Mixin for message caching and cleanup operations."""

    def _cleanup_caches(self: "ModTrackerService") -> None:
        """
        Clean up memory caches to prevent unbounded growth.

        Evicts old entries from action history, ban history, permission changes,
        and target action tracking based on configured limits.
        """
        now = datetime.now(NY_TZ)
        cleaned = 0

        # Clean action history (keep only recent actions per mod)
        for mod_id in list(self._action_history.keys()):
            for action_type in list(self._action_history[mod_id].keys()):
                actions = self._action_history[mod_id][action_type]
                if len(actions) > ACTION_HISTORY_MAX_ENTRIES:
                    # Keep most recent entries
                    self._action_history[mod_id][action_type] = sorted(actions)[-ACTION_HISTORY_MAX_ENTRIES:]
                    cleaned += len(actions) - ACTION_HISTORY_MAX_ENTRIES

        # Clean ban history (keep only recent bans per mod)
        for mod_id in list(self._ban_history.keys()):
            bans = self._ban_history[mod_id]
            if len(bans) > BAN_HISTORY_MAX_ENTRIES:
                # Sort by timestamp and keep most recent
                sorted_bans = sorted(bans.items(), key=lambda x: x[1])
                self._ban_history[mod_id] = dict(sorted_bans[-BAN_HISTORY_MAX_ENTRIES:])
                cleaned += len(bans) - BAN_HISTORY_MAX_ENTRIES

        # Clean permission changes (keep only recent per mod)
        for mod_id in list(self._permission_changes.keys()):
            changes = self._permission_changes[mod_id]
            if len(changes) > PERMISSION_CHANGES_MAX:
                self._permission_changes[mod_id] = sorted(changes)[-PERMISSION_CHANGES_MAX:]
                cleaned += len(changes) - PERMISSION_CHANGES_MAX

        # Clean target actions (keep only recent targets per mod)
        for mod_id in list(self._target_actions.keys()):
            targets = self._target_actions[mod_id]
            if len(targets) > TARGET_ACTIONS_MAX_ENTRIES:
                # Sort by most recent action and keep top entries
                sorted_targets = sorted(
                    targets.items(),
                    key=lambda x: max(t[1] for t in x[1]) if x[1] else datetime.min.replace(tzinfo=NY_TZ),
                    reverse=True
                )
                self._target_actions[mod_id] = dict(sorted_targets[:TARGET_ACTIONS_MAX_ENTRIES])
                cleaned += len(targets) - TARGET_ACTIONS_MAX_ENTRIES

        if cleaned > 0:
            logger.debug(f"Mod Tracker: Cleaned {cleaned} stale cache entries")

    async def cache_message(self: "ModTrackerService", message: discord.Message) -> None:
        """
        Cache a message from a tracked mod with its attachments.

        Args:
            message: The message to cache.
        """
        if not self.is_tracked(message.author.id):
            return

        # Download attachments
        attachment_data: List[Tuple[str, bytes]] = []
        if message.attachments:
            async with aiohttp.ClientSession() as session:
                for attachment in message.attachments[:5]:
                    try:
                        if attachment.content_type and any(
                            t in attachment.content_type
                            for t in ["image", "video", "gif"]
                        ):
                            async with session.get(attachment.url) as resp:
                                if resp.status == 200:
                                    data = await resp.read()
                                    attachment_data.append((attachment.filename, data))
                    except Exception:
                        pass

        # Create cached message
        cached = CachedMessage(
            message_id=message.id,
            author_id=message.author.id,
            channel_id=message.channel.id,
            content=message.content or "",
            cached_at=datetime.now(NY_TZ),
            attachments=attachment_data,
        )

        # Add to cache
        mod_cache = self._message_cache[message.author.id]
        mod_cache.append(cached)

        # Trim cache if too large
        if len(mod_cache) > MESSAGE_CACHE_SIZE:
            self._message_cache[message.author.id] = mod_cache[-MESSAGE_CACHE_SIZE:]

        # Clean old messages
        cutoff = datetime.now(NY_TZ) - timedelta(seconds=MESSAGE_CACHE_TTL)
        self._message_cache[message.author.id] = [
            m for m in self._message_cache[message.author.id]
            if m.cached_at > cutoff
        ]

        # Evict oldest mod's cache if we have too many mods cached (LRU)
        if len(self._message_cache) > MESSAGE_CACHE_MAX_MODS:
            oldest_mod = None
            oldest_time = None
            for mod_id, msgs in self._message_cache.items():
                if msgs:
                    msg_time = msgs[0].cached_at
                    if oldest_time is None or msg_time < oldest_time:
                        oldest_time = msg_time
                        oldest_mod = mod_id
            if oldest_mod and oldest_mod != message.author.id:
                try:
                    del self._message_cache[oldest_mod]
                except KeyError:
                    pass  # Already removed by another coroutine

    def get_cached_message(
        self: "ModTrackerService",
        message_id: int
    ) -> Optional[CachedMessage]:
        """Get a cached message by ID."""
        for mod_cache in self._message_cache.values():
            for msg in mod_cache:
                if msg.message_id == message_id:
                    return msg
        return None


__all__ = ["CacheMixin"]
