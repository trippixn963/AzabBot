"""
AzabBot - Prison Handler
========================

Handles prisoner welcome and release functionality.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, TYPE_CHECKING
from collections import OrderedDict

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
from src.core.constants import QUERY_LIMIT_MEDIUM, CASE_LOG_TIMEOUT
from src.utils.duration import format_duration_from_minutes as format_duration
from src.utils.async_utils import create_safe_task
from src.utils.retry import safe_fetch_channel

from .welcome import build_welcome_embed
from .views import build_appeal_view
from .vc_kick import handle_vc_kick

if TYPE_CHECKING:
    from src.bot import AzabBot


class PrisonHandler:
    """
    Manages prisoner welcome and release operations.

    DESIGN: Central handler for all prisoner-related events.
    Coordinates between Discord events and database.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the prison handler.

        Args:
            bot: Main bot instance
        """
        self.bot = bot
        self.config = get_config()

        # Mute Reason Tracking (OrderedDict with LRU eviction)
        self.mute_reasons: OrderedDict[Any, str] = OrderedDict()
        self._mute_reasons_limit: int = 1000

        # VC Kick Tracking (progressive timeout)
        self.vc_kick_counts: Dict[int, int] = {}

        # Concurrency Protection
        self._state_lock = asyncio.Lock()

        logger.tree("Prison Handler Loaded", [
            ("Features", "Welcome, release, VC kick"),
            ("VC Timeout", "1st warn, 2nd 5m, 3rd+ 30m"),
        ], emoji="⛓️")

    async def handle_new_prisoner(self, member: discord.Member) -> None:
        """
        Welcome a newly muted user to prison.

        DESIGN: Multi-step process:
        1. Kick from VC if connected
        2. Get mute reason from logs
        3. Create welcome embed
        4. Record mute in database
        """
        try:
            # Calculate account age for logging
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
            await handle_vc_kick(self.bot, member, self.vc_kick_counts, self._state_lock)

            # Get channels
            logs_channel = await safe_fetch_channel(self.bot, self.config.mod_logs_forum_id)
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

            # Get mute reason from cache or scan logs
            mute_reason = await self._get_mute_reason(member, logs_channel)

            # Get prisoner stats and mute record
            prisoner_stats = await self.bot.db.get_prisoner_stats(member.id)
            mute_record = self.bot.db.get_active_mute(member.id, member.guild.id)

            # Get weekly stats
            offense_count_week = self.bot.db.get_user_mute_count_week(member.id, member.guild.id)
            time_served_week = self.bot.db.get_user_time_served_week(member.id, member.guild.id)

            # Build welcome embed
            embed = build_welcome_embed(
                member=member,
                mute_record=mute_record,
                mute_reason=mute_reason,
                prisoner_stats=prisoner_stats,
                offense_count_week=offense_count_week,
                time_served_week=time_served_week,
            )

            # Create case if none exists
            await self._ensure_case_exists(member, mute_record, mute_reason)

            # Build appeal button view
            view = await build_appeal_view(self.bot, member, mute_record)

            # Send welcome message
            await prison_channel.send(member.mention, embed=embed, view=view)

            # Update presence
            if self.bot.presence:
                create_safe_task(
                    self.bot.presence.show_prisoner_arrived(
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
                ("Appeal Button", "Yes" if view else "No (< 1h)"),
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
        """
        try:
            logger.tree("Processing Prisoner Release", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
            ], emoji="🔓")

            current_duration = await self.bot.db.get_current_mute_duration(member.id)
            prisoner_stats = await self.bot.db.get_prisoner_stats(member.id)

            # Update presence
            if self.bot.presence:
                create_safe_task(
                    self.bot.presence.show_prisoner_released(
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

    async def _get_mute_reason(
        self,
        member: discord.Member,
        logs_channel: discord.abc.GuildChannel,
    ) -> Optional[str]:
        """Get mute reason from cache or scan logs."""
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

        return mute_reason

    async def _scan_logs_for_reason(
        self,
        member: discord.Member,
        logs_channel: discord.abc.GuildChannel,
    ) -> None:
        """Scan logs channel for mute reason in recent embeds."""
        if not self.bot.mute:
            return

        # Skip if logs_channel is a forum
        if isinstance(logs_channel, discord.ForumChannel):
            logger.debug("Log Scan Skipped", [("Reason", "Forum channel")])
            return

        try:
            async for message in logs_channel.history(limit=QUERY_LIMIT_MEDIUM):
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

    async def _ensure_case_exists(
        self,
        member: discord.Member,
        mute_record: Optional[Any],
        mute_reason: Optional[str],
    ) -> None:
        """Create case if none exists for this mute."""
        if not self.bot.case_log_service or not mute_record:
            return

        # Check ops guild first (where cases are created), then member's guild
        config = get_config()
        existing_case = None
        for guild_id in [config.mod_server_id, member.guild.id]:
            if guild_id:
                existing_case = self.bot.db.get_active_mute_case(member.id, guild_id)
                if existing_case:
                    break
        if existing_case:
            return

        try:
            # Get duration string
            sentence_text = "Unknown"
            if mute_record["expires_at"]:
                # Ensure both values are floats (database may store as string)
                expires_at = float(mute_record["expires_at"])
                muted_at = float(mute_record["muted_at"])
                duration_seconds = int(expires_at - muted_at)
                sentence_text = format_duration(duration_seconds // 60)
            elif mute_record["expires_at"] is None:
                sentence_text = "Permanent"

            bot_member = member.guild.get_member(self.bot.user.id)
            if bot_member:
                # Use mute_reason from log scan, fall back to database record, then default
                final_reason = (
                    mute_reason
                    or mute_record.get("reason")
                    or "Manual mute (role added directly)"
                )
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_mute(
                        user=member,
                        moderator=bot_member,
                        duration=sentence_text,
                        reason=final_reason,
                        is_extension=False,
                        evidence=None,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
                if case_info:
                    logger.tree("Case Created (Auto)", [
                        ("Action", "Mute"),
                        ("Case ID", case_info.get("case_id", "Unknown")),
                        ("User", f"{member.name} ({member.id})"),
                        ("Reason", "No existing case - created automatically"),
                    ], emoji="📋")

        except asyncio.TimeoutError:
            logger.warning("Case Log Timeout (Auto)", [
                ("Action", "Mute"),
                ("User", f"{member.name} ({member.id})"),
            ])
        except Exception as e:
            logger.error("Case Log Failed (Auto)", [
                ("Action", "Mute"),
                ("User", f"{member.name} ({member.id})"),
                ("Error", str(e)[:100]),
            ])


__all__ = ["PrisonHandler"]
