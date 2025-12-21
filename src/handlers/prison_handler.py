"""
Azab Discord Bot - Prison Handler
=================================

Handles prisoner welcome and release functionality.

This module manages:
- New prisoner welcome messages with AI roasts
- Prisoner release notifications
- VC kick with progressive timeout
- Daily prison channel cleanup
- Message cleanup after release

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, NY_TZ, EmbedColors

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.services.ai_service import AIService


# =============================================================================
# Helper Functions
# =============================================================================

def format_duration(minutes: int) -> str:
    """
    Format minutes into human-readable duration string.

    Args:
        minutes: Duration in minutes

    Returns:
        Formatted string like "2d 5h 30m" or "45m"
    """
    if not minutes:
        return "0m"
    days = minutes // 1440
    hours = (minutes % 1440) // 60
    mins = minutes % 60
    if days:
        return f"{days}d {hours}h {mins}m"
    elif hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


# =============================================================================
# Prison Handler Class
# =============================================================================

class PrisonHandler:
    """
    Manages prisoner welcome and release operations.

    DESIGN: Central handler for all prisoner-related events.
    Coordinates between Discord events, AI service, and database.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot", ai_service: "AIService") -> None:
        """
        Initialize the prison handler.

        Args:
            bot: Main bot instance
            ai_service: AI service for generating roasts
        """
        self.bot = bot
        self.ai = ai_service
        self.config = get_config()

        # =================================================================
        # Mute Reason Tracking
        # DESIGN: Stores mute reasons by user_id or username for AI context
        # =================================================================
        self.mute_reasons: Dict[Any, str] = {}

        # =================================================================
        # VC Kick Tracking
        # DESIGN: Progressive timeout - 1st warning, 2nd 5min, 3rd+ 30min
        # =================================================================
        self.vc_kick_counts: Dict[int, int] = {}

        # Start daily cleanup task
        asyncio.create_task(self._daily_cleanup_loop())

    # =========================================================================
    # Main Event Handlers
    # =========================================================================

    async def handle_new_prisoner(self, member: discord.Member) -> None:
        """
        Welcome a newly muted user to prison.

        DESIGN: Multi-step process:
        1. Kick from VC if connected
        2. Send mute notification to last active channel
        3. Get mute reason from logs
        4. Generate AI welcome message
        5. Record mute in database
        """
        try:
            logger.tree("Processing New Prisoner", [
                ("User", str(member)),
                ("User ID", str(member.id)),
            ], emoji="⛓️")

            # Handle VC kick with progressive timeout
            await self._handle_vc_kick(member)

            # Get channels
            logs_channel = self.bot.get_channel(self.config.logs_channel_id)

            # Get first prison channel
            prison_channel = None
            if self.config.prison_channel_ids:
                prison_channel = self.bot.get_channel(
                    next(iter(self.config.prison_channel_ids))
                )

            if not logs_channel or not prison_channel:
                logger.error("Required Channels Not Found", [
                    ("Logs", str(self.config.logs_channel_id)),
                    ("Prison", str(self.config.prison_channel_ids)),
                ])
                return

            # Send mute notification to user's last active channel
            mute_channel = self._get_mute_notification_channel(member)
            if mute_channel:
                await self._send_mute_notification(member, mute_channel)

            # Wait for mute embed to appear in logs
            await asyncio.sleep(5)

            # Get mute reason from cache or scan logs
            mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(
                member.name.lower()
            )

            if not mute_reason:
                await self._scan_logs_for_reason(member, logs_channel)
                mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(
                    member.name.lower()
                )

            # Get prisoner stats for personalized message
            prisoner_stats = await self.bot.db.get_prisoner_stats(member.id)

            # Generate AI welcome message
            response = await self._generate_welcome_message(
                member, mute_reason, prisoner_stats
            )

            # Create welcome embed
            embed = discord.Embed(
                title="NEW PRISONER ARRIVAL",
                description=f"{member.mention}",
                color=EmbedColors.PRISON,
            )

            if mute_reason:
                embed.add_field(
                    name="Reason",
                    value=mute_reason[:self.config.mute_reason_max_length],
                    inline=False,
                )

            if prisoner_stats["total_mutes"] > 0:
                embed.add_field(
                    name="Prison Record",
                    value=f"Visit #{prisoner_stats['total_mutes'] + 1}",
                    inline=True,
                )
                total_time = format_duration(prisoner_stats["total_minutes"] or 0)
                embed.add_field(name="Total Time Served", value=total_time, inline=True)

            embed.set_thumbnail(
                url=member.avatar.url if member.avatar else member.default_avatar.url
            )
            embed.set_footer(text=f"Developed By: {self.config.developer_name}")

            await prison_channel.send(f"{member.mention} {response}", embed=embed)

            # Update presence
            if self.bot.presence_handler:
                asyncio.create_task(
                    self.bot.presence_handler.show_prisoner_arrived(
                        username=member.name,
                        reason=mute_reason,
                        mute_count=prisoner_stats.get("total_mutes", 1),
                    )
                )

            # Record mute in database
            trigger_message = None
            if member.id in self.bot.last_messages:
                messages = self.bot.last_messages[member.id].get("messages")
                if messages:
                    trigger_message = messages[-1]

            await self.bot.db.record_mute(
                user_id=member.id,
                username=member.name,
                reason=mute_reason or "Unknown",
                muted_by=None,
                trigger_message=trigger_message,
            )

            logger.tree("Prisoner Welcome Complete", [
                ("Prisoner", str(member)),
                ("Reason", (mute_reason or "Unknown")[:50]),
                ("Visit #", str(prisoner_stats["total_mutes"] + 1)),
            ], emoji="😈")

        except Exception as e:
            logger.error("Prison Handler Error", [
                ("Location", "handle_new_prisoner"),
                ("Member", str(member)),
                ("Error", str(e)),
            ])

    async def handle_prisoner_release(self, member: discord.Member) -> None:
        """
        Handle prisoner release with farewell message.

        DESIGN: Multi-step process:
        1. Generate AI release message
        2. Post to general channel
        3. Update database
        4. Schedule message cleanup
        """
        try:
            logger.tree("Processing Prisoner Release", [
                ("User", str(member)),
                ("User ID", str(member.id)),
            ], emoji="🔓")

            general_channel = self.bot.get_channel(self.config.general_channel_id)
            if not general_channel:
                logger.error("General Channel Not Found", [
                    ("Channel ID", str(self.config.general_channel_id)),
                ])
                return

            mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(
                member.name.lower()
            )

            prisoner_stats = await self.bot.db.get_prisoner_stats(member.id)
            current_duration = await self.bot.db.get_current_mute_duration(member.id)

            # Generate AI release message
            response = await self._generate_release_message(member, mute_reason)

            # Create release embed
            embed = discord.Embed(
                title="PRISONER RELEASED",
                description=f"{member.mention}",
                color=EmbedColors.RELEASE,
            )

            if mute_reason:
                embed.add_field(
                    name="Released From",
                    value=mute_reason[:self.config.mute_reason_max_length],
                    inline=False,
                )

            if prisoner_stats["total_mutes"] > 0:
                embed.add_field(
                    name="Total Visits",
                    value=str(prisoner_stats["total_mutes"]),
                    inline=True,
                )
                time_served = format_duration(current_duration) if current_duration > 0 else "< 1 minute"
                embed.add_field(name="Time Served", value=time_served, inline=True)

            embed.set_thumbnail(
                url=member.avatar.url if member.avatar else member.default_avatar.url
            )
            embed.set_footer(text=f"Developed By: {self.config.developer_name}")

            await general_channel.send(f"{member.mention} {response}", embed=embed)

            # Update presence
            if self.bot.presence_handler:
                asyncio.create_task(
                    self.bot.presence_handler.show_prisoner_released(
                        username=member.name,
                        duration_minutes=current_duration,
                    )
                )

            # Record unmute in database
            await self.bot.db.record_unmute(user_id=member.id, unmuted_by=None)

            # Cleanup tracking data
            self.mute_reasons.pop(member.id, None)
            self.mute_reasons.pop(member.name.lower(), None)
            self.vc_kick_counts.pop(member.id, None)

            # Schedule delayed message cleanup (1 hour)
            asyncio.create_task(self._delayed_message_cleanup(member))

            logger.tree("Prisoner Release Complete", [
                ("Ex-Prisoner", str(member)),
                ("Time Served", format_duration(current_duration)),
                ("Total Visits", str(prisoner_stats["total_mutes"])),
            ], emoji="🎉")

        except Exception as e:
            logger.error("Prison Handler Error", [
                ("Location", "handle_prisoner_release"),
                ("Member", str(member)),
                ("Error", str(e)),
            ])

    # =========================================================================
    # VC Handling
    # =========================================================================

    async def _handle_vc_kick(self, member: discord.Member) -> None:
        """
        Handle VC kick with progressive timeout.

        DESIGN: Escalating punishment:
        - 1st offense: Warning only
        - 2nd offense: 5 minute timeout
        - 3rd+ offense: 30 minute timeout
        """
        if not member.voice or not member.voice.channel:
            return

        vc_name = member.voice.channel.name

        try:
            await member.move_to(None)

            # Track kick count
            self.vc_kick_counts[member.id] = self.vc_kick_counts.get(member.id, 0) + 1
            kick_count = self.vc_kick_counts[member.id]

            # Determine timeout duration
            timeout_minutes = 0
            if kick_count == 2:
                timeout_minutes = 5
            elif kick_count >= 3:
                timeout_minutes = 30

            # Apply timeout if needed
            if timeout_minutes > 0:
                try:
                    await member.timeout(
                        timedelta(minutes=timeout_minutes),
                        reason=f"Prisoner VC violation #{kick_count}"
                    )
                    logger.info("Timeout Applied", [
                        ("User", str(member)),
                        ("Duration", f"{timeout_minutes}min"),
                        ("Offense #", str(kick_count)),
                    ])
                except discord.Forbidden:
                    pass

            # Send VC kick message
            prison_channel = None
            if self.config.prison_channel_ids:
                prison_channel = self.bot.get_channel(
                    next(iter(self.config.prison_channel_ids))
                )

            if prison_channel:
                if kick_count == 1:
                    msg = f"{member.mention} Got kicked from **#{vc_name}**. No voice privileges. This is your warning."
                elif kick_count == 2:
                    msg = f"{member.mention} Kicked from **#{vc_name}** AGAIN. **5 minute timeout.**"
                else:
                    msg = f"{member.mention} Kicked from **#{vc_name}**. Offense #{kick_count}. **30 minute timeout.**"

                await prison_channel.send(msg)

            logger.tree("VC Kick", [
                ("User", str(member)),
                ("Channel", f"#{vc_name}"),
                ("Offense #", str(kick_count)),
                ("Timeout", f"{timeout_minutes}min" if timeout_minutes else "None"),
            ], emoji="🔇")

        except discord.Forbidden:
            logger.warning("VC Kick Failed (Permissions)", [
                ("User", str(member)),
            ])

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_mute_notification_channel(self, member: discord.Member) -> Optional[discord.TextChannel]:
        """Get channel for mute notification based on user's last message."""
        if member.id in self.bot.last_messages:
            channel_id = self.bot.last_messages[member.id].get("channel_id")
            if channel_id:
                return self.bot.get_channel(channel_id)
        return self.bot.get_channel(self.config.general_channel_id)

    async def _send_mute_notification(
        self,
        member: discord.Member,
        channel: discord.TextChannel,
    ) -> None:
        """Send mute notification to channel where user was active."""
        try:
            if self.ai:
                mute_announcement = await self.ai.generate_response(
                    "Someone just got muted. Mock them briefly about getting muted. Be savage but concise.",
                    member.display_name,
                    False,
                    None,
                )
            else:
                mute_announcement = "Welcome to prison!"

            embed = discord.Embed(
                title="USER MUTED",
                description=f"{member.mention} has been sent to prison.",
                color=EmbedColors.ERROR,
            )
            embed.set_thumbnail(
                url=member.avatar.url if member.avatar else member.default_avatar.url
            )
            embed.set_footer(text=f"Developed By: {self.config.developer_name}")

            await channel.send(f"{member.mention} {mute_announcement}", embed=embed)

        except Exception as e:
            logger.warning("Mute Notification Failed", [("Error", str(e))])

    async def _scan_logs_for_reason(
        self,
        member: discord.Member,
        logs_channel: discord.TextChannel,
    ) -> None:
        """Scan logs channel for mute reason in recent embeds."""
        try:
            async for message in logs_channel.history(limit=50):
                if message.embeds:
                    await self.bot.mute_handler.process_mute_embed(message)
                    if member.id in self.mute_reasons or member.name.lower() in self.mute_reasons:
                        break
        except Exception as e:
            logger.warning("Log Scan Failed", [("Error", str(e))])

    async def _generate_welcome_message(
        self,
        member: discord.Member,
        mute_reason: Optional[str],
        prisoner_stats: Dict[str, Any],
    ) -> str:
        """Generate AI welcome message for new prisoner."""
        if not self.ai:
            return "Welcome to prison!"

        if mute_reason:
            prompt = f"Welcome a prisoner jailed for: '{mute_reason}'. Mock them about their offense."
            if prisoner_stats["total_mutes"] > 0:
                total_time = format_duration(prisoner_stats["total_minutes"] or 0)
                prompt += f" This is visit #{prisoner_stats['total_mutes'] + 1}. They've spent {total_time} locked up."
        else:
            prompt = "Welcome a prisoner to jail. Mock them for getting locked up."

        return await self.ai.generate_response(
            prompt, member.display_name, True, mute_reason
        )

    async def _generate_release_message(
        self,
        member: discord.Member,
        mute_reason: Optional[str],
    ) -> str:
        """Generate AI release message for freed prisoner."""
        if not self.ai:
            return "You're free... for now."

        if mute_reason:
            prompt = f"Someone was released from prison for: '{mute_reason}'. Mock them sarcastically."
        else:
            prompt = "Someone got released from prison. Mock them about finally being free."

        return await self.ai.generate_response(
            prompt, member.display_name, False, mute_reason
        )

    # =========================================================================
    # Cleanup Tasks
    # =========================================================================

    async def _delayed_message_cleanup(self, member: discord.Member) -> None:
        """Wait 1 hour before deleting prisoner's messages from prison channel."""
        try:
            await asyncio.sleep(3600)  # 1 hour
            deleted_count = await self._delete_prisoner_messages(member)
            logger.tree("Delayed Message Cleanup", [
                ("Ex-Prisoner", str(member)),
                ("Messages Deleted", str(deleted_count)),
            ], emoji="🧹")
        except Exception as e:
            logger.error("Delayed Cleanup Error", [
                ("Member", str(member)),
                ("Error", str(e)),
            ])

    async def _delete_prisoner_messages(self, member: discord.Member) -> int:
        """Delete prisoner's messages from prison channel."""
        try:
            prison_channel = None
            if self.config.prison_channel_ids:
                prison_channel = self.bot.get_channel(
                    next(iter(self.config.prison_channel_ids))
                )

            if not prison_channel:
                return 0

            messages_to_delete = []
            two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)

            async for message in prison_channel.history(limit=self.config.prison_message_scan_limit):
                if message.author.id == member.id and message.created_at > two_weeks_ago:
                    messages_to_delete.append(message)

            if messages_to_delete:
                try:
                    await prison_channel.delete_messages(messages_to_delete)
                    return len(messages_to_delete)
                except discord.HTTPException:
                    # Fallback to individual deletion
                    count = 0
                    for message in messages_to_delete:
                        try:
                            await message.delete()
                            count += 1
                            await asyncio.sleep(1.0)
                        except Exception:
                            pass
                    return count

            return 0

        except Exception as e:
            logger.error("Message Deletion Error", [
                ("Member", str(member)),
                ("Error", str(e)),
            ])
            return 0

    async def _daily_cleanup_loop(self) -> None:
        """Background task for daily prison channel cleanup at midnight."""
        try:
            await self.bot.wait_until_ready()
            logger.info("Daily Cleanup Loop Started")

            while not self.bot.is_closed():
                try:
                    # Calculate time until next midnight
                    now = datetime.now(NY_TZ)
                    next_cleanup = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    if next_cleanup <= now:
                        next_cleanup += timedelta(days=1)

                    sleep_seconds = (next_cleanup - now).total_seconds()
                    logger.debug(f"Next cleanup scheduled in {sleep_seconds/3600:.1f} hours")

                    await asyncio.sleep(sleep_seconds)

                    # Execute cleanup
                    prison_channel = None
                    if self.config.prison_channel_ids:
                        prison_channel = self.bot.get_channel(
                            next(iter(self.config.prison_channel_ids))
                        )

                    if prison_channel:
                        deleted_count = 0
                        two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)

                        while True:
                            messages_to_delete = []
                            async for message in prison_channel.history(limit=500):
                                if message.created_at > two_weeks_ago:
                                    messages_to_delete.append(message)

                            if not messages_to_delete:
                                break

                            try:
                                for i in range(0, len(messages_to_delete), 100):
                                    batch = messages_to_delete[i:i + 100]
                                    await prison_channel.delete_messages(batch)
                                    deleted_count += len(batch)
                                    await asyncio.sleep(1)
                            except discord.HTTPException:
                                break

                            await asyncio.sleep(2)

                        logger.tree("Daily Cleanup Complete", [
                            ("Channel", f"#{prison_channel.name}"),
                            ("Deleted", str(deleted_count)),
                        ], emoji="🧹")

                except Exception as e:
                    logger.error("Cleanup Loop Error", [
                        ("Error", str(e)),
                    ])
                    await asyncio.sleep(3600)

        except Exception as e:
            logger.error("Cleanup Loop Setup Error", [
                ("Error", str(e)),
            ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["PrisonHandler", "format_duration"]
