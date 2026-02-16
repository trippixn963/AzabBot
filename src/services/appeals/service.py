"""
AzabBot - Appeal Service
========================

Service for handling ban and mute appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict

import discord

from src.core.config import get_config
from src.core.database import get_db
from src.core.logger import logger

from .helpers import HelpersMixin
from .eligibility import EligibilityMixin
from .create import CreateMixin
from .resolve import ResolveMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class AppealService(HelpersMixin, EligibilityMixin, CreateMixin, ResolveMixin):
    """
    Service for managing ban appeals.

    DESIGN:
        Ban appeals are submitted via web form and managed through the dashboard.
        Mute appeals use the separate ticket system.
        No Discord forum threads are created for appeals.
    """

    # Thread cache TTL (kept for legacy compatibility)
    THREAD_CACHE_TTL = timedelta(minutes=5)

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._forum: Optional[discord.ForumChannel] = None
        self._forum_cache_time: Optional[datetime] = None
        self._thread_cache: Dict[int, tuple[discord.Thread, datetime]] = {}

        if self.enabled:
            logger.tree("Appeal Service Initialized", [
                ("Mode", "Web Dashboard Only"),
                ("Mute Appeals", "Use ticket system"),
            ], emoji="📨")
        else:
            logger.debug("Appeal Service Disabled (no forum configured)")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if appeal system is enabled."""
        return self.config.appeal_forum_id is not None


__all__ = ["AppealService"]
