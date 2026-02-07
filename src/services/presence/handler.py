"""
AzabBot - Presence Handler
==========================

Wrapper around unified presence system with AzabBot-specific stats.
Includes prisoner event presence.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
from src.core.constants import PRESENCE_UPDATE_INTERVAL, PROMO_DURATION_MINUTES, PRESENCE_RETRY_DELAY

# Import from shared unified presence system
from shared.services.presence import BasePresenceHandler

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

PROMO_TEXT = "🌐 trippixn.com/azab"


# =============================================================================
# AzabBot Presence Handler
# =============================================================================

class PresenceHandler(BasePresenceHandler):
    """
    Presence handler configured for AzabBot with moderation stats.

    Additional features beyond base:
    - Prisoner arrived/released event presence
    """

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(
            bot,
            update_interval=PRESENCE_UPDATE_INTERVAL,
            promo_duration_minutes=PROMO_DURATION_MINUTES,
        )
        self.config = get_config()

    # =========================================================================
    # Required Implementations
    # =========================================================================

    def get_status_messages(self) -> List[str]:
        """Get moderation stats for presence rotation."""
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

            # Total tickets opened (all-time counter)
            total_tickets = 0
            for guild in self.bot.guilds:
                total_tickets += self.bot.db.get_total_tickets_opened(guild.id)
            if total_tickets > 0:
                stats.append(f"🎫 {total_tickets:,} tickets")

        except Exception as e:
            logger.debug("Stats Fetch Error", [("Error", str(e)[:50])])

        return stats

    def get_promo_text(self) -> str:
        """Return AzabBot promo text."""
        return PROMO_TEXT

    def get_timezone(self) -> ZoneInfo:
        """Return NY timezone for promo scheduling."""
        return NY_TZ

    # =========================================================================
    # Logging Hooks
    # =========================================================================

    def on_rotation_start(self) -> None:
        pass  # Logged in on_handler_ready

    def on_promo_start(self) -> None:
        pass  # Logged in on_handler_ready

    def on_promo_activated(self) -> None:
        now = datetime.now(NY_TZ)
        logger.tree("Promo Presence Activated", [
            ("Text", PROMO_TEXT),
            ("Duration", f"{self.promo_duration_minutes} minutes"),
            ("Time", now.strftime("%I:%M %p EST")),
        ], emoji="📢")

    def on_promo_ended(self) -> None:
        logger.tree("Promo Presence Ended", [
            ("Status", "Normal rotation resumed"),
        ], emoji="🔄")

    def on_handler_ready(self) -> None:
        logger.tree("Presence Handler Loaded", [
            ("Update Interval", f"{self.update_interval}s"),
            ("Promo Schedule", "Every hour on the hour"),
            ("Promo Duration", f"{self.promo_duration_minutes} minutes"),
        ], emoji="🔄")

    def on_handler_stopped(self) -> None:
        logger.tree("Presence Handler Stopped", [
            ("Status", "Tasks cancelled"),
        ], emoji="🛑")

    def on_error(self, context: str, error: Exception) -> None:
        error_msg = str(error).lower()
        if any(x in error_msg for x in ["transport", "not connected", "closed", "connection"]):
            logger.debug("Presence Connection Issue", [
                ("Context", context),
                ("Error", str(error)[:50]),
            ])
        else:
            logger.warning(context, [
                ("Error Type", type(error).__name__),
                ("Error", str(error)[:50]),
            ])

    # =========================================================================
    # Helpers
    # =========================================================================

    def _count_prisoners(self) -> int:
        """Count current prisoners across all servers."""
        count = 0
        for guild in self.bot.guilds:
            muted_role = guild.get_role(self.config.muted_role_id)
            if muted_role:
                count += len(muted_role.members)
        return count


    # =========================================================================
    # Event-Triggered Presence (AzabBot specific)
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
        if self._is_promo_active:
            logger.debug("Prisoner Presence Skipped", [("User", username or "Unknown"), ("Reason", "Promo Active")])
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
                activity=discord.CustomActivity(name=status_text),
            )

            logger.tree("Presence Updated", [
                ("Event", "Prisoner Arrived"),
                ("User", username or "Unknown"),
                ("Status", status_text),
            ], emoji="🔴")

            # Revert after delay
            await asyncio.sleep(PRESENCE_RETRY_DELAY)
            await self._update_rotating_presence()

        except Exception as e:
            self.on_error("Prisoner Arrival Presence", e)

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
        if self._is_promo_active:
            logger.debug("Release Presence Skipped", [("User", username or "Unknown"), ("Reason", "Promo Active")])
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
                activity=discord.CustomActivity(name=status_text),
            )

            logger.tree("Presence Updated", [
                ("Event", "Prisoner Released"),
                ("User", username or "Unknown"),
                ("Duration", time_str if duration_minutes else "N/A"),
                ("Status", status_text),
            ], emoji="🟢")

            # Revert after delay
            await asyncio.sleep(PRESENCE_RETRY_DELAY)
            await self._update_rotating_presence()

        except Exception as e:
            self.on_error("Prisoner Release Presence", e)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["PresenceHandler"]
