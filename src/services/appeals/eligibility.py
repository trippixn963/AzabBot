"""
AzabBot - Appeal Eligibility Mixin
==================================

Forum access and eligibility checking methods.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict

import discord

from src.core.logger import logger
from src.core.config import NY_TZ
from src.utils.retry import safe_fetch_channel

from .constants import MIN_APPEALABLE_MUTE_DURATION

if TYPE_CHECKING:
    from .service import AppealService


class EligibilityMixin:
    """Mixin for appeal eligibility and forum access."""

    # Thread cache TTL
    THREAD_CACHE_TTL = timedelta(minutes=5)

    async def _get_forum(self: "AppealService") -> Optional[discord.ForumChannel]:
        """Get the appeal forum channel with caching."""
        if not self.config.appeal_forum_id:
            return None

        now = datetime.now(NY_TZ)

        # Check cache
        if self._forum is not None and self._forum_cache_time is not None:
            if now - self._forum_cache_time < self.THREAD_CACHE_TTL:
                return self._forum

        # Fetch forum
        channel = await safe_fetch_channel(self.bot, self.config.appeal_forum_id)
        if channel is None:
            logger.warning("Appeal Forum Not Found", [
                ("Forum ID", str(self.config.appeal_forum_id)),
            ])
            return None

        if isinstance(channel, discord.ForumChannel):
            self._forum = channel
            self._forum_cache_time = now
            return self._forum

        logger.warning("Invalid Appeal Forum Channel", [
            ("Channel ID", str(self.config.appeal_forum_id)),
            ("Expected", "ForumChannel"),
            ("Got", type(channel).__name__),
        ])
        return None

    async def _get_appeal_thread(self: "AppealService", thread_id: int) -> Optional[discord.Thread]:
        """Get an appeal thread by ID with caching."""
        now = datetime.now(NY_TZ)

        # Check cache
        if thread_id in self._thread_cache:
            cached_thread, cached_at = self._thread_cache[thread_id]
            if now - cached_at < self.THREAD_CACHE_TTL:
                return cached_thread
            else:
                try:
                    del self._thread_cache[thread_id]
                except KeyError:
                    pass  # Already removed

        # Fetch thread
        channel = await safe_fetch_channel(self.bot, thread_id)
        if channel is None:
            return None

        if isinstance(channel, discord.Thread):
            self._thread_cache[thread_id] = (channel, now)
            # Evict oldest entry if cache exceeds limit (with race condition protection)
            if len(self._thread_cache) > 50:
                try:
                    oldest = min(self._thread_cache.keys(), key=lambda k: self._thread_cache[k][1])
                    del self._thread_cache[oldest]
                except (KeyError, ValueError):
                    pass  # Entry already removed by another coroutine
            return channel

        return None

    def can_appeal(self: "AppealService", case_id: str) -> tuple[bool, Optional[str], Optional[dict]]:
        """
        Check if a case can be appealed.

        Args:
            case_id: Case ID to check.

        Returns:
            Tuple of (can_appeal, reason_if_not, case_data).
            case_data is returned to avoid redundant queries.
        """
        # Check if appeals are enabled
        if not self.enabled:
            return (False, "Appeal system is not enabled", None)

        # Check if case exists
        case = self.db.get_appealable_case(case_id)
        if not case:
            return (False, "Case not found", None)

        # Check action type - only mutes can be appealed
        action_type = case.get("action_type", "")
        if action_type != "mute":
            return (False, f"Only mutes can be appealed (this is a {action_type})", None)

        # Check duration (must be >= 1 hour or permanent)
        duration = case.get("duration_seconds")
        if duration is not None and duration < MIN_APPEALABLE_MUTE_DURATION:
            hours = duration // 3600
            minutes = (duration % 3600) // 60
            min_hours = MIN_APPEALABLE_MUTE_DURATION // 3600
            return (False, f"Mutes under {min_hours} hour(s) cannot be appealed (this mute: {hours}h {minutes}m)", None)

        # Check if already appealed
        can_appeal_db, reason = self.db.can_appeal_case(case_id)
        if not can_appeal_db:
            return (False, reason, None)

        return (True, None, case)


__all__ = ["EligibilityMixin"]
