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
Version: v2.3.0
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

        # Rotating presence messages for active mode (each with emoji)
        self.active_messages = [
            "👁️ {count} prisoners",
            "😈 Torturing {count}",
            "😭 {count} crying",
            "⛓️ Locked {count}",
            "🔥 Roasting {count}",
            "💀 Destroying {count}",
            "🎪 {count} suffering"
        ]

        # Idle mode variety (each with emoji)
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
        # === Cancel Any Existing Presence Update Task ===
        # Prevents multiple loops from running simultaneously
        # If bot is restarted or loop needs to restart, cancel old task first
        if self.update_task:
            self.update_task.cancel()

        # === Start New Continuous Update Loop ===
        # Create asyncio task that runs _presence_loop in background
        # This task runs independently and doesn't block other bot operations
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
        # Infinite loop - runs until bot shutdown or task cancellation
        while True:
            try:
                # === Update Presence ===
                # Call update_presence to change bot's Discord status
                await self.update_presence()
                
                # === Wait Before Next Update ===
                # Sleep for configured interval (default 30 seconds)
                # Prevents excessive API calls to Discord
                await asyncio.sleep(int(os.getenv('PRESENCE_UPDATE_INTERVAL', '30')))
            except Exception as e:
                # === Error Handling ===
                # Log error but continue loop (don't let one failure stop all updates)
                # Truncate error message to prevent log spam
                logger.error("Presence Update", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
                # Still sleep before retrying to avoid rapid error loops
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
            # === CHECK BOT ACTIVATION STATE ===
            if self.bot.is_active:
                # === ACTIVE MODE: Bot is monitoring prisoners ===
                
                # Count current prisoners across all servers
                prisoner_count: int = self._count_prisoners()

                # === EMERGENCY MODE: Mass Arrest Detected ===
                # Trigger when 5+ prisoners and count increased since last check
                # Special presence to highlight mass muting event
                if prisoner_count >= 5 and prisoner_count > self.last_prisoner_count:
                    await self.bot.change_presence(
                        status=discord.Status.dnd,  # Red status (Do Not Disturb) for emergency
                        activity=discord.Activity(
                            type=discord.ActivityType.competing,  # "Competing in"
                            name="🚨 Mass arrest"  # Emergency message
                        )
                    )
                    self.last_prisoner_count = prisoner_count
                    return  # Exit early, emergency mode takes priority

                # === STATS MODE: Show Prison Statistics ===
                # 10% chance to display interesting stats instead of prisoner count
                # Adds variety to presence and showcases bot features
                if random.random() < 0.1:
                    # Get random stats message from database
                    stats_message = await self._get_stats_message()
                    if stats_message:
                        await self.bot.change_presence(
                            status=discord.Status.online,  # Green status (online)
                            activity=discord.Activity(
                                type=discord.ActivityType.playing,  # "Playing"
                                name=stats_message  # Stats like "1000 total mutes served"
                            )
                        )
                        self.last_prisoner_count = prisoner_count
                        return  # Exit early, stats mode displayed

                # === NORMAL ACTIVE MODE: Show Prisoner Count ===
                # Select random message template from active_messages list
                # Templates use {count} placeholder for prisoner count
                message_template = random.choice(self.active_messages)
                status_text = message_template.format(count=prisoner_count)

                # Set presence to "Watching X prisoners" with creative variations
                await self.bot.change_presence(
                    status=discord.Status.online,  # Green status (online and active)
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,  # "Watching"
                        name=status_text  # e.g., "👁️ Watching 3 prisoners"
                    )
                )
                # Store count for emergency detection on next update
                self.last_prisoner_count = prisoner_count
            else:
                # === INACTIVE MODE: Bot is Sleeping ===
                # Bot is deactivated - show idle/sleeping status
                # Select random message from idle_messages list
                status_text = random.choice(self.idle_messages)
                await self.bot.change_presence(
                    status=discord.Status.idle,  # Yellow/idle status
                    activity=discord.Activity(
                        type=discord.ActivityType.playing,  # "Playing"
                        name=status_text  # e.g., "💤 Taking a nap"
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
            # === REPEAT OFFENDER DETECTION ===
            # If user has been muted 5+ times, show special repeat offender message
            # These users get unique presence messages to highlight their frequent violations
            if mute_count >= 5 and username:
                repeat_messages = [
                    f"🔥 {username} again",      # Fire emoji for frequent offenders
                    f"🤡 {username} back",       # Clown emoji for repeat behavior
                    f"💀 Regular: {username}",   # Skull emoji for "prison regular"
                    f"🎪 {username} returned"    # Circus emoji for frequent returns
                ]
                # Randomly select one repeat offender message for variety
                status_text = random.choice(repeat_messages)
            
            # === NORMAL PRISONER ARRIVAL WITH REASON ===
            # Show username + reason for first-time or regular prisoners
            elif reason and username:
                # === Truncate Reason if Too Long ===
                # Discord status is limited in length, truncate long reasons
                max_len = 30  # Maximum characters for reason text
                if len(reason) > max_len:
                    # Cut at max_len-3 and add ellipsis (...) to indicate truncation
                    reason = reason[:max_len-3] + "..."
                # Format: "🔒 username: reason" (e.g., "🔒 JohnDoe: Spamming")
                status_text = f"🔒 {username}: {reason}"
            
            # === USERNAME ONLY (No Reason Available) ===
            elif username:
                # Fallback when reason is missing or empty
                status_text = f"🔒 {username} locked"
            
            # === GENERIC FALLBACK (No Username or Reason) ===
            else:
                # Last resort fallback message
                status_text = "🔒 New prisoner"

            # === UPDATE PRESENCE TO SHOW ARRIVAL ===
            # Set bot status to red "Do Not Disturb" to highlight event
            await self.bot.change_presence(
                status=discord.Status.dnd,  # Red status (Do Not Disturb) for emphasis
                activity=discord.Activity(
                    type=discord.ActivityType.playing,  # "Playing"
                    name=status_text  # The arrival message created above
                )
            )

            # === WAIT FOR EVENT DURATION ===
            # Keep arrival message visible for configured duration (default 5 seconds)
            # This ensures people see the event before presence returns to normal
            await asyncio.sleep(int(os.getenv('PRESENCE_EVENT_DURATION', '5')))

            # === RETURN TO NORMAL PRESENCE ===
            # After event duration, switch back to normal presence
            # This calls update_presence() which shows prisoner count or idle status
            await self.update_presence()

        except Exception as e:
            # === ERROR HANDLING ===
            # Log error but don't crash - presence updates are non-critical
            # Truncate error message to prevent log spam
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
            # === CREATE RELEASE MESSAGE WITH TIME SERVED ===
            if username and duration_minutes:
                # === FORMAT DURATION FOR DISPLAY ===
                # Convert total minutes to human-readable format (days/hours/minutes)
                # Choose largest appropriate unit for compact display
                
                if duration_minutes >= 1440:  # 1440 minutes = 24 hours = 1 day
                    # Show in days for long mutes
                    days = duration_minutes // 1440  # Integer division for whole days
                    time_str = f"{days}d"  # e.g., "5d" for 5 days
                
                elif duration_minutes >= 60:  # 60 minutes = 1 hour
                    # Show in hours for medium mutes
                    hours = duration_minutes // 60  # Integer division for whole hours
                    time_str = f"{hours}h"  # e.g., "3h" for 3 hours
                
                else:  # Less than 1 hour
                    # Show in minutes for short mutes
                    time_str = f"{duration_minutes}m"  # e.g., "30m" for 30 minutes

                # Format: "🔓 username (time)" (e.g., "🔓 JohnDoe (5d)")
                status_text = f"🔓 {username} ({time_str})"
            
            # === USERNAME ONLY (No Duration Available) ===
            elif username:
                # Fallback when duration is unknown or zero
                status_text = f"🔓 {username} freed"
            
            # === GENERIC FALLBACK (No Username or Duration) ===
            else:
                # Last resort fallback message
                status_text = "🔓 Released"

            # === UPDATE PRESENCE TO SHOW RELEASE ===
            # Set bot status to green "Online" to celebrate release
            await self.bot.change_presence(
                status=discord.Status.online,  # Green status (online) for positive event
                activity=discord.Activity(
                    type=discord.ActivityType.playing,  # "Playing"
                    name=status_text  # The release message created above
                )
            )

            # === WAIT FOR EVENT DURATION ===
            # Keep release message visible for configured duration (default 5 seconds)
            # This ensures people see the event before presence returns to normal
            await asyncio.sleep(int(os.getenv('PRESENCE_EVENT_DURATION', '5')))

            # === RETURN TO NORMAL PRESENCE ===
            # After event duration, switch back to normal presence
            # This calls update_presence() which shows prisoner count or idle status
            await self.update_presence()

        except Exception as e:
            # === ERROR HANDLING ===
            # Log error but don't crash - presence updates are non-critical
            # Truncate error message to prevent log spam
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
        # Iterate through all Discord servers the bot is connected to
        for guild in self.bot.guilds:
            # Get the muted role object from this server
            # self.bot.muted_role_id is configured in .env
            muted_role: Optional[discord.Role] = guild.get_role(self.bot.muted_role_id)
            # If role exists in this server, count members who have it
            if muted_role:
                count += len(muted_role.members)  # muted_role.members is list of users with role
        return count  # Total muted users across all servers

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
            # === GET PRISON STATISTICS FROM DATABASE ===
            # Retrieve comprehensive stats from database (total mutes, time served, etc.)
            stats = await self.bot.db.get_prison_stats()

            # === VALIDATE STATS AVAILABILITY ===
            # If no stats available (empty dict or None), return None
            if not stats:
                return None

            # === BUILD LIST OF STATS MESSAGE OPTIONS ===
            # Create list of formatted stats messages to choose from
            # Each stat is only included if it has a meaningful value (> 0)
            stats_messages = []

            # === TOTAL MUTES STAT ===
            # Show total number of completed mutes in database
            if stats.get('total_mutes', 0) > 0:
                stats_messages.append(f"📊 {stats['total_mutes']} mutes")

            # === TOTAL TIME SERVED STAT ===
            # Show cumulative time all prisoners have served
            # Format as days or hours depending on magnitude
            if stats.get('total_time_minutes', 0) > 0:
                hours = stats['total_time_minutes'] // 60  # Convert minutes to hours
                if hours >= 24:
                    # Show in days for large values (24+ hours)
                    days = hours // 24  # Convert hours to days
                    stats_messages.append(f"⏰ {days} days served")
                else:
                    # Show in hours for smaller values (< 24 hours)
                    stats_messages.append(f"⏰ {hours}h served")

            # === UNIQUE PRISONERS STAT ===
            # Show number of distinct users who have been muted
            if stats.get('unique_prisoners', 0) > 0:
                stats_messages.append(f"💀 {stats['unique_prisoners']} tracked")

            # === MOST COMMON MUTE REASON STAT ===
            # Show the most frequent mute reason with occurrence count
            if stats.get('most_common_reason'):
                # Truncate long reasons to fit in Discord presence (max 15 chars)
                reason = stats['most_common_reason'][:15]
                count = stats.get('most_common_reason_count', 0)
                # Format: "🎯 Spamming (42x)" showing reason and count
                stats_messages.append(f"🎯 {reason} ({count}x)")

            # === LONGEST SENTENCE STAT ===
            # Show the longest mute duration on record
            try:
                # Query database for longest completed mute
                longest = await self.bot.db.get_longest_sentence()
                if longest and longest.get('duration_minutes', 0) > 0:
                    hours = longest['duration_minutes'] // 60  # Convert to hours
                    if hours >= 24:
                        # Show in days for long records (24+ hours)
                        days = hours // 24  # Convert to days
                        stats_messages.append(f"👑 Record {days}d")
                    else:
                        # Show in hours for shorter records (< 24 hours)
                        stats_messages.append(f"👑 Record {hours}h")
            except:
                # === SILENT FAILURE FOR LONGEST SENTENCE ===
                # If query fails, skip this stat (don't crash entire function)
                # Just continue with other available stats
                pass

            # === SELECT RANDOM STAT MESSAGE ===
            # Return random stat from available options for variety
            # If no stats were added to list, return None
            return random.choice(stats_messages) if stats_messages else None

        except Exception as e:
            # === ERROR HANDLING ===
            # Log error but return None instead of crashing
            # Stats display is non-critical, bot continues without stats
            logger.error("Stats Message", str(e)[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
            return None