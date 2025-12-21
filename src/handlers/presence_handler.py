"""
Azab Discord Bot - Presence Handler
===================================

Manages dynamic Discord rich presence updates.

DESIGN:
    The bot's presence (status message) provides at-a-glance information
    about its current state. Active mode shows prisoner counts and taunts,
    while inactive mode shows sleeping messages.

    Special presence updates trigger on prisoner arrival/release for
    immediate visual feedback to server members.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
import random
from typing import Optional, List, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Presence Handler Class
# =============================================================================

class PresenceHandler:
    """
    Manages Discord rich presence for the bot.

    DESIGN:
        Rotates through status messages on a 30-second interval.
        Adapts content based on bot state (active/inactive).
        Shows special messages for prisoner events.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        update_task: Background task for presence rotation.
        last_prisoner_count: Cached count for mass arrest detection.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the presence handler.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.update_task: Optional[asyncio.Task] = None
        self.last_prisoner_count: int = 0

        # -------------------------------------------------------------------------
        # Active Mode Messages
        # -------------------------------------------------------------------------

        self.active_messages: List[str] = [
            "{count} prisoners",
            "Torturing {count}",
            "{count} crying",
            "Locked {count}",
            "Roasting {count}",
            "Destroying {count}",
            "{count} suffering",
        ]

        # -------------------------------------------------------------------------
        # Idle Mode Messages
        # -------------------------------------------------------------------------

        self.idle_messages: List[str] = [
            "Napping",
            "Off duty",
            "Resting",
            "Dreaming",
            "Break time",
            "Sleeping",
            "Off shift",
        ]

    # =========================================================================
    # Presence Loop
    # =========================================================================

    async def start_presence_loop(self) -> None:
        """
        Start the automatic presence update loop.

        DESIGN:
            Cancels any existing loop before starting new one.
            Runs in background until bot shutdown.
        """
        if self.update_task:
            self.update_task.cancel()

        self.update_task = asyncio.create_task(self._presence_loop())

        logger.tree("Presence Loop Started", [
            ("Interval", "30 seconds"),
            ("Active Messages", str(len(self.active_messages))),
            ("Idle Messages", str(len(self.idle_messages))),
        ], emoji="🔄")

    async def _presence_loop(self) -> None:
        """
        Main presence update loop.

        DESIGN:
            Updates presence every 30 seconds.
            Catches and logs errors without crashing.
            Continues running until explicitly cancelled.
        """
        while True:
            try:
                await self.update_presence()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Presence Loop Error", [
                    ("Error", str(e)[:50]),
                ])
                await asyncio.sleep(30)

    # =========================================================================
    # Presence Updates
    # =========================================================================

    async def update_presence(self) -> None:
        """
        Update bot's Discord presence based on current state.

        DESIGN:
            Active mode: Shows prisoner count with random taunts.
            Mass arrest mode: DND status when 5+ prisoners arrive.
            Stats mode: 10% chance to show aggregate stats.
            Inactive mode: Idle status with sleeping messages.
        """
        try:
            if not self.bot.disabled:
                prisoner_count = self._count_prisoners()

                # -----------------------------------------------------------------
                # Emergency Mode for Mass Arrests
                # -----------------------------------------------------------------

                if prisoner_count >= 5 and prisoner_count > self.last_prisoner_count:
                    await self.bot.change_presence(
                        status=discord.Status.dnd,
                        activity=discord.Activity(
                            type=discord.ActivityType.competing,
                            name="Mass arrest",
                        ),
                    )
                    self.last_prisoner_count = prisoner_count
                    return

                # -----------------------------------------------------------------
                # Stats Mode (10% Chance)
                # -----------------------------------------------------------------

                if random.random() < 0.1:
                    stats_message = await self._get_stats_message()
                    if stats_message:
                        await self.bot.change_presence(
                            status=discord.Status.online,
                            activity=discord.Activity(
                                type=discord.ActivityType.playing,
                                name=stats_message,
                            ),
                        )
                        self.last_prisoner_count = prisoner_count
                        return

                # -----------------------------------------------------------------
                # Normal Active Mode
                # -----------------------------------------------------------------

                message_template = random.choice(self.active_messages)
                status_text = message_template.format(count=prisoner_count)

                await self.bot.change_presence(
                    status=discord.Status.online,
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=status_text,
                    ),
                )
                self.last_prisoner_count = prisoner_count

            else:
                # -----------------------------------------------------------------
                # Inactive Mode
                # -----------------------------------------------------------------

                status_text = random.choice(self.idle_messages)
                await self.bot.change_presence(
                    status=discord.Status.idle,
                    activity=discord.Activity(
                        type=discord.ActivityType.playing,
                        name=status_text,
                    ),
                )

        except Exception as e:
            logger.error("Presence Update Failed", [
                ("Error", str(e)[:50]),
            ])

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

        DESIGN:
            DND status signals active enforcement.
            Repeat offenders get special callout messages.
            Reverts to normal presence after 5 seconds.

        Args:
            username: Prisoner's display name.
            reason: Mute reason for context.
            mute_count: Number of times this user has been muted.
        """
        try:
            # Special messages for repeat offenders
            if mute_count >= 5 and username:
                repeat_messages = [
                    f"{username} again",
                    f"{username} back",
                    f"Regular: {username}",
                    f"{username} returned",
                ]
                status_text = random.choice(repeat_messages)
            elif reason and username:
                max_len = 30
                if len(reason) > max_len:
                    reason = reason[:max_len - 3] + "..."
                status_text = f"{username}: {reason}"
            elif username:
                status_text = f"{username} locked"
            else:
                status_text = "New prisoner"

            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=status_text,
                ),
            )

            logger.tree("Presence Updated", [
                ("Event", "Prisoner Arrived"),
                ("Status", status_text),
            ], emoji="🔴")

            await asyncio.sleep(5)
            await self.update_presence()

        except Exception as e:
            logger.error("Prisoner Arrival Presence Failed", [
                ("Username", username or "Unknown"),
                ("Error", str(e)[:50]),
            ])

    async def show_prisoner_released(
        self,
        username: Optional[str] = None,
        duration_minutes: int = 0,
    ) -> None:
        """
        Temporarily show when a prisoner is released.

        DESIGN:
            Online status signals completion.
            Duration shown in compact format (d/h/m).
            Reverts to normal presence after 5 seconds.

        Args:
            username: Released user's display name.
            duration_minutes: How long they were muted.
        """
        try:
            if username and duration_minutes:
                if duration_minutes >= 1440:
                    days = duration_minutes // 1440
                    time_str = f"{days}d"
                elif duration_minutes >= 60:
                    hours = duration_minutes // 60
                    time_str = f"{hours}h"
                else:
                    time_str = f"{duration_minutes}m"
                status_text = f"{username} ({time_str})"
            elif username:
                status_text = f"{username} freed"
            else:
                status_text = "Released"

            await self.bot.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=status_text,
                ),
            )

            logger.tree("Presence Updated", [
                ("Event", "Prisoner Released"),
                ("Status", status_text),
            ], emoji="🟢")

            await asyncio.sleep(5)
            await self.update_presence()

        except Exception as e:
            logger.error("Prisoner Release Presence Failed", [
                ("Username", username or "Unknown"),
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _count_prisoners(self) -> int:
        """
        Count current prisoners across all servers.

        DESIGN:
            Iterates all guilds looking for muted role members.
            Returns 0 if muted role doesn't exist in a guild.

        Returns:
            Total count of muted members across all guilds.
        """
        count = 0
        for guild in self.bot.guilds:
            muted_role = guild.get_role(self.config.muted_role_id)
            if muted_role:
                count += len(muted_role.members)
        return count

    async def _get_stats_message(self) -> Optional[str]:
        """
        Get stats-based presence message from database.

        DESIGN:
            Queries aggregate stats for varied presence content.
            Returns None if no stats available.

        Returns:
            Random stats message or None.
        """
        try:
            stats_messages: List[str] = []

            row = self.bot.db.fetchone(
                """SELECT COUNT(*) as total_mutes,
                   COALESCE(SUM(duration_minutes), 0) as total_minutes
                   FROM prisoner_history"""
            )

            if row:
                total_mutes = row["total_mutes"] or 0
                total_minutes = row["total_minutes"] or 0

                if total_mutes > 0:
                    stats_messages.append(f"{total_mutes} mutes")

                if total_minutes > 0:
                    hours = total_minutes // 60
                    if hours >= 24:
                        days = hours // 24
                        stats_messages.append(f"{days}d served")
                    else:
                        stats_messages.append(f"{hours}h served")

            return random.choice(stats_messages) if stats_messages else None

        except Exception as e:
            logger.error("Stats Message Query Failed", [
                ("Error", str(e)[:50]),
            ])
            return None


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["PresenceHandler"]
