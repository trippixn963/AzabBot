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

        # DESIGN: Variety of status messages prevents Discord presence from feeling stale
        # 7 different active messages rotate randomly, keeping presence fresh
        # {count} placeholder gets replaced with actual prisoner count at runtime
        # Creative, intimidating messages fit bot's "torture" personality
        self.active_messages: list[str] = [
            "👁️ {count} prisoners",
            "😈 Torturing {count}",
            "😭 {count} crying",
            "⛓️ Locked {count}",
            "🔥 Roasting {count}",
            "💀 Destroying {count}",
            "🎪 {count} suffering"
        ]

        # DESIGN: Idle messages for when bot is deactivated/sleeping
        # Shows bot is present but not actively monitoring
        # Different messages add personality during downtime
        self.idle_messages: list[str] = [
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
        # DESIGN: Cancel existing loop before starting new one
        # Prevents multiple loops from running simultaneously (memory leak)
        # Can happen if bot reconnects or restarts without full shutdown
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
                # DESIGN: 30-second update interval balances freshness vs Discord rate limits
                # Too frequent (< 10s) triggers rate limiting
                # Too slow (> 60s) makes presence feel outdated
                # 30s is sweet spot for dynamic status without hitting limits
                update_interval: int = int(os.getenv('PRESENCE_UPDATE_INTERVAL', '30'))
                await asyncio.sleep(update_interval)
            except Exception as e:
                logger.error("Presence Update", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
                # DESIGN: Still sleep on error to prevent rapid retry loops
                # Prevents flooding Discord API if presence updates consistently fail
                update_interval: int = int(os.getenv('PRESENCE_UPDATE_INTERVAL', '30'))
                await asyncio.sleep(update_interval)

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

                # DESIGN: Emergency mode for sudden mass arrests (5+ prisoners)
                # Threshold of 5 prevents triggering on normal activity
                # > last_prisoner_count prevents showing every update when count stays high
                # "Competing" activity type shows bright green bar in Discord for urgency
                # DND status (red dot) signals high-priority situation
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

                # DESIGN: 10% chance to show stats instead of regular message
                # Adds variety to presence without overwhelming with data
                # random.random() returns 0.0-1.0, < 0.1 means 10% chance
                # Shows interesting prison metrics (total mutes, longest sentence, etc.)
                if random.random() < 0.1:
                    stats_message: Optional[str] = await self._get_stats_message()
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

                # DESIGN: Normal active mode - show prisoner count with creative message
                # random.choice picks one of 7 active_messages for variety
                # format() replaces {count} placeholder with actual prisoner count
                message_template: str = random.choice(self.active_messages)
                status_text: str = message_template.format(count=prisoner_count)

                await self.bot.change_presence(
                    status=discord.Status.online,
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=status_text
                    )
                )
                self.last_prisoner_count = prisoner_count
            else:
                # DESIGN: Inactive mode shows bot is sleeping/off duty
                # random.choice picks one of 7 idle_messages for personality
                # Status.idle (orange dot) indicates bot is present but not monitoring
                # "Playing" activity type works best for single-line idle messages
                status_text: str = random.choice(self.idle_messages)
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
            # DESIGN: Special messages for repeat offenders (5+ mutes)
            # Threshold of 5 identifies chronic troublemakers vs accidental mutes
            # Mocking messages ("again", "back") add personality and call out repeat behavior
            # random.choice provides variety so repeat offenders see different messages
            if mute_count >= 5 and username:
                repeat_messages: list[str] = [
                    f"🔥 {username} again",
                    f"🤡 {username} back",
                    f"💀 Regular: {username}",
                    f"🎪 {username} returned"
                ]
                status_text: str = random.choice(repeat_messages)

            # DESIGN: Show username with truncated mute reason
            # Discord presence has ~128 char limit, 30 chars for reason leaves room for username
            # "..." suffix indicates truncation so users know there's more context
            # Format: "🔒 JohnDoe: Spamming chat with..."
            elif reason and username:
                max_len: int = 30
                if len(reason) > max_len:
                    reason = reason[:max_len-3] + "..."
                status_text: str = f"🔒 {username}: {reason}"

            elif username:
                status_text: str = f"🔒 {username} locked"

            else:
                status_text: str = "🔒 New prisoner"

            # DESIGN: Temporary presence update with DND status (red dot)
            # DND signals urgent event (new prisoner arrival)
            # "Playing" activity type fits single-line status format
            # Lasts 5 seconds (configurable) then returns to normal presence
            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=status_text
                )
            )

            # DESIGN: 5-second display duration balances visibility vs spam
            # Long enough for users to notice event, short enough to not clutter
            event_duration: int = int(os.getenv('PRESENCE_EVENT_DURATION', '5'))
            await asyncio.sleep(event_duration)
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
                # DESIGN: Format time served for compact Discord presence display
                # Priority: days > hours > minutes (show largest unit only)
                # 1440 minutes = 1 day, compact format keeps presence short
                # Examples: "5d" (5 days), "3h" (3 hours), "30m" (30 minutes)
                if duration_minutes >= 1440:
                    days: int = duration_minutes // 1440
                    time_str: str = f"{days}d"

                elif duration_minutes >= 60:
                    hours: int = duration_minutes // 60
                    time_str: str = f"{hours}h"

                else:
                    time_str: str = f"{duration_minutes}m"

                status_text: str = f"🔓 {username} ({time_str})"

            elif username:
                status_text: str = f"🔓 {username} freed"

            else:
                status_text: str = "🔓 Released"

            # DESIGN: Temporary presence update with online status (green dot)
            # Green indicates positive event (prisoner freed)
            # Displays for 5 seconds then returns to normal presence
            await self.bot.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name=status_text
                )
            )

            event_duration: int = int(os.getenv('PRESENCE_EVENT_DURATION', '5'))
            await asyncio.sleep(event_duration)
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
        # DESIGN: Iterate through all guilds bot is in for multi-server support
        # Most bots are single-server, but this scales if bot is added to multiple servers
        # get_role() returns None if role doesn't exist in that guild (handles missing config)
        # len(muted_role.members) is O(1) since Discord caches member lists
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
            # DESIGN: Query database for aggregate prison statistics
            # Returns dict with keys: total_mutes, total_time_minutes, unique_prisoners, most_common_reason
            stats: Optional[dict[str, Any]] = await self.bot.db.get_prison_stats()

            if not stats:
                return None

            # DESIGN: Build list of formatted stat messages
            # Each stat type gets its own emoji and compact format
            # List allows random.choice to pick one for variety
            stats_messages: list[str] = []

            # Total mutes tracked (lifetime count)
            if stats.get('total_mutes', 0) > 0:
                stats_messages.append(f"📊 {stats['total_mutes']} mutes")

            # DESIGN: Total time served across all prisoners
            # Convert minutes to days/hours for readability
            # Days shown if >= 24 hours (more impressive stat)
            if stats.get('total_time_minutes', 0) > 0:
                hours: int = stats['total_time_minutes'] // 60
                if hours >= 24:
                    days: int = hours // 24
                    stats_messages.append(f"⏰ {days} days served")
                else:
                    stats_messages.append(f"⏰ {hours}h served")

            # Unique prisoners tracked (number of different users muted)
            if stats.get('unique_prisoners', 0) > 0:
                stats_messages.append(f"💀 {stats['unique_prisoners']} tracked")

            # DESIGN: Most common mute reason with occurrence count
            # Truncate reason to 15 chars to fit in Discord presence
            # Shows what users are getting muted for most often
            if stats.get('most_common_reason'):
                reason: str = stats['most_common_reason'][:15]
                count: int = stats.get('most_common_reason_count', 0)
                stats_messages.append(f"🎯 {reason} ({count}x)")

            # DESIGN: Longest sentence as "record" stat
            # Separate query since it's more expensive (needs sorting)
            # Wrapped in try-except since this query can fail independently
            try:
                longest: Optional[dict[str, Any]] = await self.bot.db.get_longest_sentence()
                if longest and longest.get('duration_minutes', 0) > 0:
                    hours: int = longest['duration_minutes'] // 60
                    if hours >= 24:
                        days: int = hours // 24
                        stats_messages.append(f"👑 Record {days}d")
                    else:
                        stats_messages.append(f"👑 Record {hours}h")
            except:
                # DESIGN: Silently skip longest sentence if query fails
                # Don't let this optional stat block other stats from showing
                pass

            # DESIGN: Return random stat message for variety
            # Each presence update shows different stat, keeping it fresh
            return random.choice(stats_messages) if stats_messages else None

        except Exception as e:
            logger.error("Stats Message", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
            return None
