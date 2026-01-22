"""
Azab Discord Bot - Presence Handler
===================================

Wrapper around unified presence system with AzabBot-specific stats.
Includes prisoner event presence and midnight tasks.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
from src.core.constants import PRESENCE_UPDATE_INTERVAL, PROMO_DURATION_MINUTES

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
    - Midnight tasks (banner refresh, guild protection)
    """

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(
            bot,
            update_interval=PRESENCE_UPDATE_INTERVAL,
            promo_duration_minutes=PROMO_DURATION_MINUTES,
        )
        self.config = get_config()
        self._last_midnight_date: Optional[str] = None

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

            # Total tickets
            row = self.bot.db.fetchone("SELECT COUNT(*) as count FROM tickets")
            if row and row["count"] > 0:
                stats.append(f"🎫 {row['count']:,} tickets")

        except Exception as e:
            logger.debug(f"Stats fetch error: {e}")

        return stats

    def get_promo_text(self) -> str:
        """Return AzabBot promo text."""
        return PROMO_TEXT

    def get_timezone(self):
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
            logger.debug(f"{context} (Connection Issue)", [
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
    # Override Rotation Loop for Midnight Tasks
    # =========================================================================

    async def _rotation_loop(self) -> None:
        """Background task that updates presence periodically and handles midnight tasks."""
        await self.bot.wait_until_ready()

        self.on_rotation_start()

        while self._running:
            try:
                await asyncio.sleep(self.update_interval)

                # Skip if promo is active
                if self._is_promo_active:
                    continue

                await self._update_rotating_presence()
                await self._check_midnight_tasks()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.on_error("Rotation Loop", e)
                await asyncio.sleep(self.update_interval)

    # =========================================================================
    # Midnight Tasks
    # =========================================================================

    async def _check_midnight_tasks(self) -> None:
        """Run daily tasks at midnight EST."""
        try:
            now = datetime.now(NY_TZ)
            today = now.strftime("%Y-%m-%d")

            # Check if it's a new day and within first hour
            if self._last_midnight_date != today and now.hour == 0:
                self._last_midnight_date = today

                # Guild protection check
                try:
                    await self.bot._leave_unauthorized_guilds()
                except Exception as e:
                    logger.warning("Guild Protection Check Failed", [
                        ("Error", str(e)[:50]),
                    ])

                logger.tree("Midnight Tasks Complete", [
                    ("Date", today),
                    ("Tasks", "Guild check"),
                ], emoji="🌙")

        except Exception as e:
            logger.error("Midnight Tasks Failed", [
                ("Error", str(e)[:50]),
            ])

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
                activity=discord.CustomActivity(name=status_text),
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
                activity=discord.CustomActivity(name=status_text),
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
            self.on_error("Prisoner Release Presence", e)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["PresenceHandler"]
