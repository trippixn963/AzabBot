"""
Azab Discord Bot - Presence Handler
===================================

Manages dynamic Discord rich presence updates with rotating status
and hourly promotional presence.

Features:
- Rotating status showing moderation stats
- Hourly promotional presence (trippixn.com/azab for 10 mins)
- Event-triggered presence for prisoner arrivals/releases
- Clean error handling for connection issues

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

        logger.tree("Presence Handler Started", [
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

    async def _get_rotating_status(self) -> str:
        """
        Get the current rotating status text.

        Cycles through various stats - always shows real numbers.
        """
        # List of stat getters
        stat_getters = [
            self._get_prisoners_status,
            self._get_mutes_today_status,
            self._get_tickets_status,
            self._get_cases_status,
            self._get_total_mutes_status,
            self._get_total_bans_status,
            self._get_total_warns_status,
            self._get_week_mutes_status,
        ]

        self._presence_index = (self._presence_index + 1) % len(stat_getters)
        getter = stat_getters[self._presence_index]

        # Handle both sync and async getters
        if asyncio.iscoroutinefunction(getter):
            return await getter()
        return getter()

    def _get_prisoners_status(self) -> str:
        """Get current prisoners count status."""
        count = self._count_prisoners()
        return f"🔒 {count} prisoner{'s' if count != 1 else ''}" if count > 0 else "🔓 0 prisoners"

    async def _get_mutes_today_status(self) -> str:
        """Get today's mutes count status."""
        try:
            today_start = datetime.now(NY_TZ).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp()

            row = self.bot.db.fetchone(
                """SELECT COUNT(*) as count FROM mute_history
                   WHERE muted_at >= ?""",
                (today_start,)
            )
            count = row["count"] if row else 0
            return f"⚡ {count} mute{'s' if count != 1 else ''} today"
        except Exception:
            return "⚡ 0 mutes today"

    async def _get_tickets_status(self) -> str:
        """Get open tickets count status."""
        try:
            row = self.bot.db.fetchone(
                """SELECT COUNT(*) as count FROM tickets
                   WHERE status IN ('open', 'claimed')"""
            )
            count = row["count"] if row else 0
            return f"🎫 {count} open ticket{'s' if count != 1 else ''}"
        except Exception:
            return "🎫 0 open tickets"

    async def _get_cases_status(self) -> str:
        """Get total cases count status."""
        try:
            row = self.bot.db.fetchone(
                """SELECT COUNT(*) as count FROM cases"""
            )
            count = row["count"] if row else 0
            return f"📋 {count:,} cases logged"
        except Exception:
            return "📋 0 cases logged"

    async def _get_total_mutes_status(self) -> str:
        """Get total mutes ever count."""
        try:
            row = self.bot.db.fetchone(
                """SELECT COUNT(*) as count FROM mute_history"""
            )
            count = row["count"] if row else 0
            return f"🔇 {count:,} total mutes"
        except Exception:
            return "🔇 0 total mutes"

    async def _get_total_bans_status(self) -> str:
        """Get total bans count."""
        try:
            row = self.bot.db.fetchone(
                """SELECT COUNT(*) as count FROM cases WHERE action_type = 'ban'"""
            )
            count = row["count"] if row else 0
            return f"🔨 {count:,} bans issued"
        except Exception:
            return "🔨 0 bans issued"

    async def _get_total_warns_status(self) -> str:
        """Get total warns count."""
        try:
            row = self.bot.db.fetchone(
                """SELECT COUNT(*) as count FROM cases WHERE action_type = 'warn'"""
            )
            count = row["count"] if row else 0
            return f"⚠️ {count:,} warnings given"
        except Exception:
            return "⚠️ 0 warnings given"

    async def _get_week_mutes_status(self) -> str:
        """Get this week's mutes count."""
        try:
            week_start = datetime.now(NY_TZ).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            # Go back to start of week (Monday)
            days_since_monday = week_start.weekday()
            week_start = week_start.timestamp() - (days_since_monday * 86400)

            row = self.bot.db.fetchone(
                """SELECT COUNT(*) as count FROM mute_history
                   WHERE muted_at >= ?""",
                (week_start,)
            )
            count = row["count"] if row else 0
            return f"📊 {count} mutes this week"
        except Exception:
            return "📊 0 mutes this week"

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
            logger.info("📢 Promo Presence Ended - Normal Presence Restored")
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
