"""
Azab Discord Bot - Presence Handler
===================================

Manages dynamic Discord rich presence with rotating status.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
from src.core.constants import PRESENCE_UPDATE_INTERVAL, PROMO_DURATION_MINUTES
from src.utils.async_utils import create_safe_task

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Promotional presence text
PROMO_TEXT = "🌐 trippixn.com/azab"


# =============================================================================
# Presence Handler Class
# =============================================================================

class PresenceHandler:
    """
    Manages Discord rich presence for the bot.

    Features:
    - Rotating status messages about moderation activity
    - Hourly promotional presence window
    - Event-triggered presence for prisoner events
    """

    def __init__(self, bot: "AzabBot") -> None:
        """Initialize the presence handler."""
        self.bot = bot
        self.config = get_config()

        # Background tasks
        self._presence_task: Optional[asyncio.Task] = None
        self._promo_task: Optional[asyncio.Task] = None

        # State tracking
        self._presence_index: int = 0
        self._promo_active: bool = False
        self._last_banner_refresh_date: Optional[str] = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the presence update and promo scheduler loops."""
        # Set initial presence immediately
        await self._update_rotating_presence()

        # Start presence update loop (using create_safe_task for error logging)
        self._presence_task = create_safe_task(self._presence_loop(), "Presence Update Loop")

        # Start promo scheduler
        self._promo_task = create_safe_task(self._promo_loop(), "Promo Scheduler Loop")

        logger.tree("Presence Handler Loaded", [
            ("Update Interval", f"{PRESENCE_UPDATE_INTERVAL}s"),
            ("Promo Schedule", "Every hour on the hour"),
            ("Promo Duration", f"{PROMO_DURATION_MINUTES} minutes"),
        ], emoji="🔄")

    async def stop(self) -> None:
        """Stop all presence tasks."""
        if self._presence_task:
            self._presence_task.cancel()
            try:
                await self._presence_task
            except asyncio.CancelledError:
                pass
            self._presence_task = None

        if self._promo_task:
            self._promo_task.cancel()
            try:
                await self._promo_task
            except asyncio.CancelledError:
                pass
            self._promo_task = None

        logger.tree("Presence Handler Stopped", [
            ("Status", "Tasks cancelled"),
        ], emoji="🛑")

    # =========================================================================
    # Main Presence Loop
    # =========================================================================

    async def _presence_loop(self) -> None:
        """Background task that updates presence periodically."""
        while True:
            try:
                await asyncio.sleep(PRESENCE_UPDATE_INTERVAL)
                await self._update_rotating_presence()
                await self._check_midnight_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log_presence_error("Presence Loop Error", e)
                await asyncio.sleep(PRESENCE_UPDATE_INTERVAL)

    async def _update_rotating_presence(self) -> None:
        """Update presence with rotating status messages."""
        # Skip during promo window
        if self._promo_active:
            return

        try:
            status_text = await self._get_rotating_status()

            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=status_text
            )

            await self.bot.change_presence(
                status=discord.Status.online,
                activity=activity
            )

            logger.debug(f"Rotating presence updated: {status_text}")

        except Exception as e:
            self._log_presence_error("Presence Update Failed", e)

    def _get_stats(self) -> list[str]:
        """
        Get list of all-time stat strings to rotate through.

        Returns only stats with values > 0.
        """
        stats = []

        try:
            # Current prisoners
            prisoners = self._count_prisoners()
            if prisoners > 0:
                stats.append(f"🔒 {prisoners:,} prisoners")

            # Total cases logged
            row = self.bot.db.fetchone("SELECT COUNT(*) as count FROM cases")
            if row and row["count"] > 0:
                stats.append(f"📋 {row['count']:,} cases logged")

            # Total mutes (all time)
            row = self.bot.db.fetchone("SELECT COUNT(*) as count FROM mute_history")
            if row and row["count"] > 0:
                stats.append(f"🔇 {row['count']:,} mutes")

            # Total bans
            row = self.bot.db.fetchone(
                "SELECT COUNT(*) as count FROM cases WHERE action_type = 'ban'"
            )
            if row and row["count"] > 0:
                stats.append(f"🔨 {row['count']:,} bans")

            # Total warns
            row = self.bot.db.fetchone(
                "SELECT COUNT(*) as count FROM cases WHERE action_type = 'warn'"
            )
            if row and row["count"] > 0:
                stats.append(f"⚠️ {row['count']:,} warnings")

            # Total tickets
            row = self.bot.db.fetchone("SELECT COUNT(*) as count FROM tickets")
            if row and row["count"] > 0:
                stats.append(f"🎫 {row['count']:,} tickets")

        except Exception as e:
            logger.debug(f"Stats fetch error: {e}")

        return stats

    async def _get_rotating_status(self) -> str:
        """Get the current rotating status text from all-time stats."""
        stats = self._get_stats()

        if not stats:
            logger.debug("No stats available, using promo fallback")
            return PROMO_TEXT

        self._presence_index = self._presence_index % len(stats)
        status = stats[self._presence_index]
        self._presence_index += 1

        return status

    def _count_prisoners(self) -> int:
        """Count current prisoners across all servers."""
        count = 0
        for guild in self.bot.guilds:
            muted_role = guild.get_role(self.config.muted_role_id)
            if muted_role:
                count += len(muted_role.members)
        return count

    # =========================================================================
    # Promotional Presence
    # =========================================================================

    async def _promo_loop(self) -> None:
        """Background loop that triggers promo presence on the hour."""
        while True:
            try:
                now = datetime.now(NY_TZ)
                # Calculate seconds until next hour
                minutes_until_hour = 60 - now.minute
                seconds_until_hour = minutes_until_hour * 60 - now.second

                # Wait until next hour
                await asyncio.sleep(seconds_until_hour)

                # Show promo presence
                await self._show_promo_presence()

                # Wait for promo duration
                await asyncio.sleep(PROMO_DURATION_MINUTES * 60)

                # Restore normal presence
                await self._restore_normal_presence()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._promo_active = False
                self._log_presence_error("Promo Loop Error", e)
                await asyncio.sleep(60)

    async def _show_promo_presence(self) -> None:
        """Show promotional presence."""
        try:
            self._promo_active = True

            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=PROMO_TEXT
            )
            await self.bot.change_presence(
                status=discord.Status.online,
                activity=activity
            )

            now = datetime.now(NY_TZ)
            logger.tree("Promo Presence Activated", [
                ("Text", PROMO_TEXT),
                ("Duration", f"{PROMO_DURATION_MINUTES} minutes"),
                ("Time", now.strftime("%I:%M %p EST")),
            ], emoji="📢")

        except Exception as e:
            self._log_presence_error("Promo Presence Failed", e)
            self._promo_active = False

    async def _restore_normal_presence(self) -> None:
        """Restore normal presence after promo ends."""
        try:
            self._promo_active = False
            await self._update_rotating_presence()

            logger.tree("Promo Presence Ended", [
                ("Status", "Normal rotation resumed"),
            ], emoji="🔄")

        except Exception as e:
            self._log_presence_error("Restore Presence Failed", e)
            self._promo_active = False

    # =========================================================================
    # Event-Triggered Presence
    # =========================================================================

    async def show_prisoner_arrived(
        self,
        username: Optional[str] = None,
        reason: Optional[str] = None,
        mute_count: int = 1,
    ) -> None:
        """
        Temporarily show when a new prisoner arrives.

        Args:
            username: Prisoner's display name.
            reason: Mute reason for context.
            mute_count: Number of times this user has been muted.
        """
        # Skip during promo
        if self._promo_active:
            logger.debug(f"Prisoner arrival presence skipped (promo active): {username}")
            return

        try:
            # Build status text
            if mute_count >= 5 and username:
                status_text = f"🔄 {username} (repeat)"
            elif username:
                status_text = f"🔒 {username} locked"
            else:
                status_text = "🔒 New prisoner"

            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=status_text,
                ),
            )

            logger.tree("Presence Updated", [
                ("Event", "Prisoner Arrived"),
                ("User", username or "Unknown"),
                ("Status", status_text),
            ], emoji="🔴")

            # Revert after delay
            await asyncio.sleep(5)
            await self._update_rotating_presence()

        except Exception as e:
            self._log_presence_error("Prisoner Arrival Presence Failed", e)

    async def show_prisoner_released(
        self,
        username: Optional[str] = None,
        duration_minutes: int = 0,
    ) -> None:
        """
        Temporarily show when a prisoner is released.

        Args:
            username: Released user's display name.
            duration_minutes: How long they were muted.
        """
        # Skip during promo
        if self._promo_active:
            logger.debug(f"Prisoner release presence skipped (promo active): {username}")
            return

        try:
            # Format duration
            if duration_minutes >= 1440:
                time_str = f"{duration_minutes // 1440}d"
            elif duration_minutes >= 60:
                time_str = f"{duration_minutes // 60}h"
            else:
                time_str = f"{duration_minutes}m"

            # Build status text
            if username and duration_minutes:
                status_text = f"🔓 {username} freed ({time_str})"
            elif username:
                status_text = f"🔓 {username} freed"
            else:
                status_text = "🔓 Prisoner released"

            await self.bot.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=status_text,
                ),
            )

            logger.tree("Presence Updated", [
                ("Event", "Prisoner Released"),
                ("User", username or "Unknown"),
                ("Duration", time_str if duration_minutes else "N/A"),
                ("Status", status_text),
            ], emoji="🟢")

            # Revert after delay
            await asyncio.sleep(5)
            await self._update_rotating_presence()

        except Exception as e:
            self._log_presence_error("Prisoner Release Presence Failed", e)

    # =========================================================================
    # Midnight Tasks
    # =========================================================================

    async def _check_midnight_tasks(self) -> None:
        """Run daily tasks at midnight EST."""
        try:
            now = datetime.now(NY_TZ)
            today = now.strftime("%Y-%m-%d")

            # Check if it's a new day and within first hour
            if self._last_banner_refresh_date != today and now.hour == 0:
                self._last_banner_refresh_date = today

                # Refresh banner
                from src.utils.banner import refresh_banner
                await refresh_banner()

                logger.tree("Midnight Tasks Complete", [
                    ("Date", today),
                    ("Task", "Banner refreshed"),
                ], emoji="🌙")

        except Exception as e:
            logger.error("Midnight Tasks Failed", [
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Error Handling
    # =========================================================================

    def _log_presence_error(self, context: str, error: Exception) -> None:
        """Log presence errors appropriately based on type."""
        error_msg = str(error).lower()

        # Connection errors during shutdown/reconnection - debug level
        if any(x in error_msg for x in ["transport", "not connected", "closed", "connection"]):
            logger.debug(f"{context} (Connection Issue)", [
                ("Error", str(error)[:50]),
            ])
        else:
            logger.warning(context, [
                ("Error Type", type(error).__name__),
                ("Error", str(error)[:50]),
            ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["PresenceHandler"]
