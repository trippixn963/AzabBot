"""
Azab Discord Bot - Prison Handler
=================================

Handles prisoner welcome and release functionality.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, TYPE_CHECKING
from collections import OrderedDict

from src.core.logger import logger
from src.core.config import get_config, NY_TZ, EmbedColors
from src.utils.footer import set_footer
from src.utils.rate_limiter import rate_limit
from src.utils.duration import format_duration_from_minutes as format_duration
from src.utils.async_utils import create_safe_task
from src.utils.retry import safe_fetch_channel

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Prison Handler Class
# =============================================================================

class PrisonHandler:
    """
    Manages prisoner welcome and release operations.

    DESIGN: Central handler for all prisoner-related events.
    Coordinates between Discord events and database.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the prison handler.

        Args:
            bot: Main bot instance
        """
        self.bot = bot
        self.config = get_config()

        # =================================================================
        # Mute Reason Tracking (OrderedDict with LRU eviction)
        # DESIGN: Stores mute reasons by user_id or username for context
        # =================================================================
        self.mute_reasons: OrderedDict[Any, str] = OrderedDict()
        self._mute_reasons_limit: int = 1000  # Max entries

        # =================================================================
        # VC Kick Tracking
        # DESIGN: Progressive timeout - 1st warning, 2nd 5min, 3rd+ 30min
        # =================================================================
        self.vc_kick_counts: Dict[int, int] = {}

        # =================================================================
        # Concurrency Protection
        # DESIGN: Lock for thread-safe access to shared dicts
        # =================================================================
        self._state_lock = asyncio.Lock()

        # Start daily cleanup task
        create_safe_task(self._daily_cleanup_loop(), "Prison Daily Cleanup")

        logger.tree("Prison Handler Loaded", [
            ("Features", "Welcome, release, VC kick"),
            ("VC Timeout", "1st warn, 2nd 5m, 3rd+ 30m"),
        ], emoji="⛓️")

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
        4. Create welcome embed
        5. Record mute in database
        """
        try:
            # Calculate account age
            now = datetime.now(NY_TZ)
            created = member.created_at.replace(tzinfo=timezone.utc) if member.created_at.tzinfo is None else member.created_at
            age_days = (now - created).days
            if age_days < 30:
                account_age = f"{age_days}d"
            elif age_days < 365:
                account_age = f"{age_days // 30}mo"
            else:
                account_age = f"{age_days // 365}y {(age_days % 365) // 30}mo"

            logger.tree("Processing New Prisoner", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Account Age", account_age),
            ], emoji="⛓️")

            # Handle VC kick with progressive timeout
            await self._handle_vc_kick(member)

            # Get channels (use safe_fetch to handle cache misses)
            logs_channel = await safe_fetch_channel(self.bot, self.config.mod_logs_forum_id)

            # Get first prison channel
            prison_channel = None
            if self.config.prison_channel_ids:
                prison_channel = await safe_fetch_channel(
                    self.bot, next(iter(self.config.prison_channel_ids))
                )

            if not logs_channel or not prison_channel:
                logger.error("Required Channels Not Found", [
                    ("Logs", str(self.config.mod_logs_forum_id)),
                    ("Prison", str(next(iter(self.config.prison_channel_ids)) if self.config.prison_channel_ids else "None")),
                ])
                return

            # Wait for mute embed to appear in logs
            await asyncio.sleep(self.config.presence_retry_delay)

            # Get mute reason from cache or scan logs (with lock for thread-safety)
            async with self._state_lock:
                mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(
                    member.name.lower()
                )

            if not mute_reason:
                await self._scan_logs_for_reason(member, logs_channel)
                async with self._state_lock:
                    mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(
                        member.name.lower()
                    )

            # Get prisoner stats for personalized message
            prisoner_stats = await self.bot.db.get_prisoner_stats(member.id)

            # Get mute info for sentence duration
            guild = member.guild
            mute_record = self.bot.db.get_active_mute(member.id, guild.id)
            sentence_text = None
            if mute_record and mute_record["expires_at"]:
                # Calculate duration from muted_at to expires_at
                duration_seconds = int(mute_record["expires_at"] - mute_record["muted_at"])
                duration_minutes = duration_seconds // 60
                sentence_text = format_duration(duration_minutes)
            elif mute_record:
                sentence_text = "Permanent"

            # Create welcome embed
            visit_num = prisoner_stats['total_mutes'] + 1
            embed = discord.Embed(
                title="🔒 Arrived to Prison",
                color=EmbedColors.GOLD,
            )

            embed.add_field(name="Prisoner", value=member.mention, inline=True)

            if sentence_text:
                embed.add_field(name="Sentence", value=f"`{sentence_text}`", inline=True)

            if prisoner_stats["total_mutes"] > 0:
                total_time = format_duration(prisoner_stats["total_minutes"] or 0)
                embed.add_field(name="Visit #", value=f"`{visit_num}`", inline=True)
                embed.add_field(name="Total Time Served", value=f"`{total_time}`", inline=True)


            embed.set_thumbnail(
                url=member.avatar.url if member.avatar else member.default_avatar.url
            )
            set_footer(embed)

            await prison_channel.send(member.mention, embed=embed)

            # Update presence
            if self.bot.presence_handler:
                create_safe_task(
                    self.bot.presence_handler.show_prisoner_arrived(
                        username=member.name,
                        reason=mute_reason,
                        mute_count=prisoner_stats.get("total_mutes", 1),
                    ),
                    name="presence_prisoner_arrived",
                )

            # Record mute in database
            trigger_message = None
            msg_data = self.bot.last_messages.get(member.id)
            if msg_data:
                messages = msg_data.get("messages")
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
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Reason", (mute_reason or "Unknown")[:50]),
                ("Visit #", str(prisoner_stats["total_mutes"] + 1)),
            ], emoji="😈")

        except Exception as e:
            logger.error("Prison Handler Error", [
                ("Location", "handle_new_prisoner"),
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Error", str(e)),
            ])

    async def handle_prisoner_release(self, member: discord.Member) -> None:
        """
        Handle prisoner release cleanup (no automated message).

        DESIGN: Only handles cleanup - /unmute command sends its own embed.
        1. Update database
        2. Cleanup tracking data
        3. Schedule message cleanup
        """
        try:
            logger.tree("Processing Prisoner Release", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
            ], emoji="🔓")

            current_duration = await self.bot.db.get_current_mute_duration(member.id)
            prisoner_stats = await self.bot.db.get_prisoner_stats(member.id)

            # Update presence
            if self.bot.presence_handler:
                create_safe_task(
                    self.bot.presence_handler.show_prisoner_released(
                        username=member.name,
                        duration_minutes=current_duration,
                    ),
                    name="presence_prisoner_released",
                )

            # Record unmute in database
            await self.bot.db.record_unmute(user_id=member.id, unmuted_by=None)

            # Cleanup tracking data (with lock for thread-safety)
            async with self._state_lock:
                self.mute_reasons.pop(member.id, None)
                self.mute_reasons.pop(member.name.lower(), None)
                self.vc_kick_counts.pop(member.id, None)

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

        logger.tree("Prison Handler: _handle_vc_kick Called", [
            ("Member", f"{member.name} ({member.id})"),
            ("VC Channel", vc_name),
            ("Current Kick Count", str(self.vc_kick_counts.get(member.id, 0))),
        ], emoji="📝")

        try:
            await member.move_to(None)

            # Track kick count (with lock for thread-safety)
            async with self._state_lock:
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
                    logger.tree("Timeout Applied", [
                        ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                        ("ID", str(member.id)),
                        ("Duration", f"{timeout_minutes}min"),
                        ("Offense #", str(kick_count)),
                    ], emoji="⏱️")
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
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Channel", f"#{vc_name}"),
                ("Offense #", str(kick_count)),
                ("Timeout", f"{timeout_minutes}min" if timeout_minutes else "None"),
            ], emoji="🔇")

        except discord.Forbidden:
            logger.warning("VC Kick Failed (Permissions)", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("VC", vc_name),
            ])

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _scan_logs_for_reason(
        self,
        member: discord.Member,
        logs_channel: discord.abc.GuildChannel,
    ) -> None:
        """Scan logs channel for mute reason in recent embeds."""
        if not self.bot.mute:
            return

        # Skip if logs_channel is a forum (forums don't have history)
        if isinstance(logs_channel, discord.ForumChannel):
            logger.debug(f"Log scan skipped - logs channel is a forum")
            return

        try:
            async for message in logs_channel.history(limit=50):
                if message.embeds:
                    await self.bot.mute.process_mute_embed(message)
                    if member.id in self.mute_reasons or member.name.lower() in self.mute_reasons:
                        break
        except Exception as e:
            logger.warning("Log Scan Failed", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("ID", str(member.id)),
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Cleanup Tasks
    # =========================================================================

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
                                    await rate_limit("bulk_operation")
                            except discord.HTTPException:
                                break

                            await rate_limit("bulk_operation")

                        logger.tree("Daily Cleanup Complete", [
                            ("Channel", f"#{prison_channel.name}"),
                            ("Deleted", str(deleted_count)),
                        ], emoji="🧹")

                except Exception as e:
                    logger.error("Cleanup Loop Error", [
                        ("Error", str(e)),
                    ])
                    await asyncio.sleep(self.config.hourly_task_interval)

        except Exception as e:
            logger.error("Cleanup Loop Setup Error", [
                ("Error", str(e)),
            ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["PrisonHandler", "format_duration"]
