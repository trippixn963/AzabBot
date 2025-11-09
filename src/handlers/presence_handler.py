"""
Azab Discord Bot - Presence Handler
===================================

Manages dynamic Discord rich presence updates based on bot state and events.

Features:
- Active/Inactive status display with rotating messages
- Real-time prisoner count when active
- Special notifications for mute/unmute events
- Stats-based presence updates with database queries
- Emergency mode for mass arrests (5+ prisoners)
- Automatic presence updates (30-second intervals)
- Repeat offender highlighting
- Time served display on release

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
import os
import random
from typing import Optional, Any

from src.core.logger import logger


class PresenceHandler:
    """
    Manages Discord rich presence for the bot.

    Updates the bot's status based on:
    - Bot activation state (active/sleeping)
    - Current prisoner count
    - Mute/unmute events
    - Stats and achievements
    """

    def __init__(self, bot: Any) -> None:
        """
        Initialize the presence handler.

        Args:
            bot: The Discord bot instance
        """
        self.bot: Any = bot
        self.update_task: Optional[asyncio.Task] = None
        self.last_prisoner_count: int = 0

        self.active_messages = [
            "👁️ {count} prisoners",
            "😈 Torturing {count}",
            "😭 {count} crying",
            "⛓️ Locked {count}",
            "🔥 Roasting {count}",
            "💀 Destroying {count}",
            "🎪 {count} suffering"
        ]

        self.idle_messages = [
            "💤 Napping",
            "😴 Off duty",
            "🌙 Resting",
            "💭 Dreaming",
            "☕ Break time",
            "🛌 Sleeping",
            "🌃 Off shift"
        ]

    async def start_presence_loop(self) -> None:
        """
        Start the automatic presence update loop.

        Creates an asyncio task that continuously updates the bot's Discord status
        every 30 seconds (configurable). Ensures only one loop runs at a time by
        canceling any existing loop before starting a new one.
        """
        if self.update_task:
            self.update_task.cancel()

        self.update_task = asyncio.create_task(self._presence_loop())
        logger.info("Started presence update loop")

    async def _presence_loop(self) -> None:
        """
        Main presence update loop that runs continuously.

        This infinite loop updates the bot's Discord presence every 30 seconds.
        Shows different statuses based on:
        - Bot active/inactive state
        - Number of current prisoners
        - Prison statistics
        - Emergency situations (mass arrests)

        Loop runs until bot shuts down or task is cancelled.
        Error handling ensures loop continues even if individual updates fail.
        """
        while True:
            try:
                await self.update_presence()
                await asyncio.sleep(int(os.getenv('PRESENCE_UPDATE_INTERVAL', '30')))
            except Exception as e:
                logger.error("Presence Update", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
                await asyncio.sleep(int(os.getenv('PRESENCE_UPDATE_INTERVAL', '30')))

    async def update_presence(self) -> None:
        """
        Update bot's Discord presence based on current state.

        Dynamically sets bot status to reflect current activity:
        - Active mode: Shows prisoner count with rotating creative messages
        - Emergency mode: "Mass arrest" when 5+ prisoners appear suddenly
        - Stats mode: Shows prison statistics (10% chance)
        - Inactive mode: Shows sleeping/idle messages

        Presence types:
        - "Watching" for prisoner monitoring (active)
        - "Playing" for stats and idle messages
        - "Competing" for emergency situations
        """
        try:
            if self.bot.is_active:
                prisoner_count: int = self._count_prisoners()

                if prisoner_count >= 5 and prisoner_count > self.last_prisoner_count:
                    await self.bot.change_presence(
                        status=discord.Status.dnd,
                        activity=discord.Activity(
                            type=discord.ActivityType.competing,
                            name="🚨 Mass arrest"
                        )
                    )
                    self.last_prisoner_count = prisoner_count
                    return

                if random.random() < 0.1:
                    stats_message = await self._get_stats_message()
                    if stats_message:
                        await self.bot.change_presence(
                            status=discord.Status.online,
                            activity=discord.Activity(
                                type=discord.ActivityType.playing,
                                name=stats_message
                            )
                        )
                        self.last_prisoner_count = prisoner_count
                        return

                message_template = random.choice(self.active_messages)
                status_text = message_template.format(count=prisoner_count)

                await self.bot.change_presence(
                    status=discord.Status.online,
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=status_text
                    )
                )
                self.last_prisoner_count = prisoner_count
            else:
                status_text = random.choice(self.idle_messages)
                await self.bot.change_presence(
                    status=discord.Status.idle,
                    activity=discord.Activity(
                        type=discord.ActivityType.playing,
                        name=status_text
                    )
                )
        except Exception as e:
            logger.error("Presence Update", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])

    async def show_prisoner_arrived(self, username: str = None, reason: str = None, mute_count: int = 1) -> None:
        """
        Temporarily show when a new prisoner arrives with their mute reason.

        Changes the bot's Discord presence to highlight a new prisoner arrival
        for 5 seconds (configurable), then returns to normal presence. Special
        messages are shown for repeat offenders (5+ mutes).

        Args:
            username: The prisoner's username (e.g., "JohnDoe")
            reason: The reason they were muted (e.g., "Spamming")
            mute_count: How many times this user has been muted (for repeat offender detection)

        Examples of status text generated:
            - First time: "🔒 JohnDoe: Spamming"
            - Repeat offender: "🔥 JohnDoe again"
        """
        try:
            if mute_count >= 5 and username:
                repeat_messages = [
                    f"🔥 {username} again",
                    f"🤡 {username} back",
                    f"💀 Regular: {username}",
                    f"🎪 {username} returned"
                ]
                status_text = random.choice(repeat_messages)

            elif reason and username:
                max_len = 30
                if len(reason) > max_len:
                    reason = reason[:max_len-3] + "..."
                status_text = f"🔒 {username}: {reason}"

            elif username:
                status_text = f"🔒 {username} locked"

            else:
                status_text = "🔒 New prisoner"

            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=status_text
                )
            )

            await asyncio.sleep(int(os.getenv('PRESENCE_EVENT_DURATION', '5')))
            await self.update_presence()

        except Exception as e:
            logger.error("Prisoner Arrival Presence", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])

    async def show_prisoner_released(self, username: str = None, duration_minutes: int = 0) -> None:
        """
        Temporarily show when a prisoner is released with their name and time served.

        Changes the bot's Discord presence to celebrate a prisoner release for 5 seconds
        (configurable), showing the username and total time they spent muted. Then returns
        to normal presence.

        Args:
            username: The prisoner's username (e.g., "JohnDoe")
            duration_minutes: Total minutes they were muted (e.g., 1440 for 1 day)

        Examples of status text generated:
            - "🔓 JohnDoe (5d)" - Released after 5 days
            - "🔓 JohnDoe (3h)" - Released after 3 hours
            - "🔓 JohnDoe (30m)" - Released after 30 minutes
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

                status_text = f"🔓 {username} ({time_str})"

            elif username:
                status_text = f"🔓 {username} freed"

            else:
                status_text = "🔓 Released"

            await self.bot.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=status_text
                )
            )

            await asyncio.sleep(int(os.getenv('PRESENCE_EVENT_DURATION', '5')))
            await self.update_presence()

        except Exception as e:
            logger.error("Prisoner Release Presence", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])

    def _count_prisoners(self) -> int:
        """
        Count the current number of prisoners (muted users) across all servers.

        Iterates through all guilds (Discord servers) the bot is in and counts
        how many members have the configured muted role. Used for presence display.

        Returns:
            int: Total number of users with the muted role across all servers
        """
        count: int = 0
        for guild in self.bot.guilds:
            muted_role: Optional[discord.Role] = guild.get_role(self.bot.muted_role_id)
            if muted_role:
                count += len(muted_role.members)
        return count

    async def _get_stats_message(self) -> Optional[str]:
        """
        Get interesting stats-based presence messages from database.

        Queries the database for various prison statistics and formats them into
        compact messages suitable for Discord presence display. Returns a random
        stat from available options for variety.

        Returns:
            Optional[str]: Formatted stats message with emoji (e.g., "📊 1000 mutes") or None if stats unavailable
        """
        try:
            stats = await self.bot.db.get_prison_stats()

            if not stats:
                return None

            stats_messages = []

            if stats.get('total_mutes', 0) > 0:
                stats_messages.append(f"📊 {stats['total_mutes']} mutes")

            if stats.get('total_time_minutes', 0) > 0:
                hours = stats['total_time_minutes'] // 60
                if hours >= 24:
                    days = hours // 24
                    stats_messages.append(f"⏰ {days} days served")
                else:
                    stats_messages.append(f"⏰ {hours}h served")

            if stats.get('unique_prisoners', 0) > 0:
                stats_messages.append(f"💀 {stats['unique_prisoners']} tracked")

            if stats.get('most_common_reason'):
                reason = stats['most_common_reason'][:15]
                count = stats.get('most_common_reason_count', 0)
                stats_messages.append(f"🎯 {reason} ({count}x)")

            try:
                longest = await self.bot.db.get_longest_sentence()
                if longest and longest.get('duration_minutes', 0) > 0:
                    hours = longest['duration_minutes'] // 60
                    if hours >= 24:
                        days = hours // 24
                        stats_messages.append(f"👑 Record {days}d")
                    else:
                        stats_messages.append(f"👑 Record {hours}h")
            except:
                pass

            return random.choice(stats_messages) if stats_messages else None

        except Exception as e:
            logger.error("Stats Message", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
            return None
