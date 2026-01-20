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

from .helpers import HelpersMixin
from .eligibility import EligibilityMixin
from .create import CreateMixin
from .resolve import ResolveMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class AppealService(HelpersMixin, EligibilityMixin, CreateMixin, ResolveMixin):
    """
    Service for managing ban and mute appeals.

    DESIGN:
        Appeals are created in a dedicated forum channel in the mods server.
        Each appeal gets its own thread using the original case ID.
        All bans can be appealed, mutes over 6 hours can be appealed.
    """

    # Thread cache TTL
    THREAD_CACHE_TTL = timedelta(minutes=5)

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._forum: Optional[discord.ForumChannel] = None
        self._forum_cache_time: Optional[datetime] = None
        self._thread_cache: Dict[int, tuple[discord.Thread, datetime]] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if appeal system is enabled."""
        return self.config.appeal_forum_id is not None


__all__ = ["AppealService"]
