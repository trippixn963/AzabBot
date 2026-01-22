"""
AzabBot - Mod Tracker Service
=============================

Service for tracking moderator activities in forum threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Tuple, Dict
from collections import defaultdict
import asyncio

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db

# Import from local package modules
from .constants import PRIORITY_NORMAL
from .helpers import CachedMessage, QueueItem

# Import all mixins
from .logs import ModTrackerLogsMixin
from .queue import QueueMixin
from .cache import CacheMixin
from .bulk_detection import BulkDetectionMixin
from .scheduler import SchedulerMixin
from .threads import ThreadsMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Mod Tracker Service
# =============================================================================

class ModTrackerService(
    ModTrackerLogsMixin,
    QueueMixin,
    CacheMixin,
    BulkDetectionMixin,
    SchedulerMixin,
    ThreadsMixin,
):
    """
    Service for tracking moderator activities.

    DESIGN:
        Each tracked mod has a forum thread in the mod server.
        All activities are logged to their thread with embeds.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
        _forum: Cached forum channel reference.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the mod tracker service.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._forum: Optional[discord.ForumChannel] = None
        self._forum_cached_at: Optional[datetime] = None
        self._scheduler_healthy: bool = False
        self._last_scan_time: Optional[datetime] = None
        self._consecutive_failures: int = 0

        # Inactivity tracking: mod_id -> last action time
        self._last_action: Dict[int, datetime] = {}

        # Message cache: mod_id -> list of cached messages
        self._message_cache: Dict[int, List[CachedMessage]] = defaultdict(list)

        # Bulk action tracking: mod_id -> action_type -> list of timestamps
        self._action_history: Dict[int, Dict[str, List[datetime]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Ban history for suspicious pattern detection: mod_id -> {target_id: ban_time}
        self._ban_history: Dict[int, Dict[int, datetime]] = defaultdict(dict)

        # Permission change tracking: mod_id -> list of timestamps
        self._permission_changes: Dict[int, List[datetime]] = defaultdict(list)

        # Target harassment tracking: mod_id -> {target_id: list of (action, timestamp)}
        self._target_actions: Dict[int, Dict[int, List[Tuple[str, datetime]]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Priority queue for message sending
        self._message_queue: List[QueueItem] = []
        self._queue_lock = asyncio.Lock()
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._queue_running = False

        logger.tree("Mod Tracker Service Created", [
            ("Enabled", str(self.enabled)),
        ], emoji="👁️")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if mod tracking is enabled."""
        return (
            self.config.mod_server_id is not None and
            self.config.mod_logs_forum_id is not None and
            self.config.moderation_role_id is not None
        )

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self) -> dict:
        """
        Check the health of the mod tracker service.

        Returns:
            Dict with health status info including:
            - enabled: Whether service is configured
            - forum_accessible: Whether forum channel is reachable
            - scheduler_healthy: Whether scheduler is running
            - last_scan_time: When last scan ran
            - consecutive_failures: Number of consecutive failures
            - tracked_mods_count: Number of tracked moderators
        """
        health = {
            "enabled": self.enabled,
            "forum_accessible": False,
            "scheduler_healthy": self._scheduler_healthy,
            "last_scan_time": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "consecutive_failures": self._consecutive_failures,
            "tracked_mods_count": 0,
        }

        if not self.enabled:
            return health

        # Check forum accessibility
        try:
            forum = await self._get_forum()
            health["forum_accessible"] = forum is not None
        except Exception:
            health["forum_accessible"] = False

        # Count tracked mods
        try:
            tracked = self.db.get_all_tracked_mods()
            health["tracked_mods_count"] = len(tracked)
        except Exception:
            pass

        return health

    def invalidate_cache(self) -> None:
        """
        Invalidate all cached data.

        Useful for recovery after errors or manual refresh.
        """
        self._forum = None
        self._forum_cached_at = None
        logger.info("Mod Tracker: Cache invalidated")

    # =========================================================================
    # Embed Builder Helpers
    # =========================================================================

    def _create_embed(
        self,
        title: str,
        color: int = EmbedColors.INFO,
    ) -> discord.Embed:
        """
        Create a standardized embed with NY timezone.

        Args:
            title: Embed title.
            color: Embed color.

        Returns:
            Configured embed.
        """
        now = datetime.now(NY_TZ)
        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=now,
        )
        return embed

    def _add_mod_field(
        self,
        embed: discord.Embed,
        mod: discord.Member,
    ) -> None:
        """
        Add moderator info field to embed.

        Args:
            embed: The embed to modify.
            mod: The moderator.
        """
        embed.set_author(
            name=f"{mod.display_name}",
            icon_url=mod.display_avatar.url,
        )

    def _format_peak_hours(self, mod_id: int) -> str:
        """
        Format peak activity hours for display.

        Args:
            mod_id: The moderator's ID.

        Returns:
            Formatted string like "2 PM (45), 8 PM (32), 10 PM (28)" or "No data yet".
        """
        peak_hours = self.db.get_peak_hours(mod_id, top_n=3)
        if not peak_hours:
            return "No data yet"

        formatted = []
        for hour, count in peak_hours:
            # Convert 24h to 12h format
            if hour == 0:
                time_str = "12 AM"
            elif hour < 12:
                time_str = f"{hour} AM"
            elif hour == 12:
                time_str = "12 PM"
            else:
                time_str = f"{hour - 12} PM"
            formatted.append(f"{time_str} ({count})")

        return ", ".join(formatted)

    # =========================================================================
    # Send Log Helper
    # =========================================================================

    async def _send_log(
        self,
        mod_id: int,
        embed: discord.Embed,
        action_name: str,
        view: Optional[discord.ui.View] = None,
        priority: int = PRIORITY_NORMAL,
    ) -> bool:
        """
        Queue a log embed to a mod's tracking thread.

        Uses the priority queue system so that security alerts can
        bypass regular logs during mass events/raids.

        Args:
            mod_id: The moderator's ID.
            embed: The embed to send.
            action_name: Name of the action for logging.
            view: Optional view with buttons.
            priority: Queue priority (default NORMAL).

        Returns:
            True if queued successfully, False otherwise.
        """
        if not self.enabled:
            return False

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return False

        # Queue the message for priority processing
        await self._enqueue(
            thread_id=tracked["thread_id"],
            embed=embed,
            priority=priority,
            view=view,
            is_alert=False,
        )

        # Increment action count immediately (stats tracking)
        self.db.increment_mod_action_count(mod_id)

        # Track hourly activity
        current_hour = datetime.now(NY_TZ).hour
        self.db.increment_hourly_activity(mod_id, current_hour)

        logger.debug(f"Mod Tracker: Log Queued - Mod {mod_id}, Action: {action_name}")
        return True
