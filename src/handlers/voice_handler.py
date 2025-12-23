"""
Azab Discord Bot - Voice Handler
=================================

Handles voice-related events and enforcement.

- Muted user VC restriction enforcement
- Voice activity logging delegation

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import timedelta
from typing import TYPE_CHECKING

import discord

from src.core.config import get_config
from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import AzabBot


class VoiceHandler:
    """
    Handles voice state changes and enforcement.

    Responsibilities:
    - Enforce VC restrictions for muted users
    - Delegate voice logging to appropriate services
    """

    def __init__(self, bot: "AzabBot") -> None:
        """Initialize the voice handler."""
        self.bot = bot
        self.config = get_config()

    async def handle_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """
        Main handler for voice state updates.

        Args:
            member: The member whose voice state changed.
            before: Previous voice state.
            after: New voice state.
        """
        # Check muted user VC restriction first
        await self._enforce_muted_vc_restriction(member, before, after)

        # Server logging service
        await self._log_voice_to_server_logs(member, before, after)

    async def _enforce_muted_vc_restriction(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """
        Enforce voice channel restriction for muted users.

        If a muted user joins a voice channel:
        1. Disconnect them immediately
        2. Apply 1-hour Discord timeout
        3. Log comprehensively (tree, server logs, case log)
        """
        # Only check when joining a voice channel
        if before.channel is not None or after.channel is None:
            return

        # Check if user has the muted role
        muted_role = member.guild.get_role(self.config.muted_role_id)
        if not muted_role or muted_role not in member.roles:
            return

        channel_name = after.channel.name if after.channel else "Unknown"

        # -----------------------------------------------------------------
        # 1. Disconnect from voice channel
        # -----------------------------------------------------------------
        try:
            await member.move_to(None, reason="Muted users are not allowed in voice channels")
        except Exception as e:
            logger.error("Failed to Disconnect Muted User from VC", [
                ("User", str(member)),
                ("Error", str(e)[:50]),
            ])
            return

        # -----------------------------------------------------------------
        # 2. Apply 1-hour Discord timeout
        # -----------------------------------------------------------------
        timeout_duration = timedelta(hours=1)

        try:
            await member.timeout(timeout_duration, reason="Attempted to join voice channel while muted")
        except Exception as e:
            logger.error("Failed to Timeout Muted User", [
                ("User", str(member)),
                ("Error", str(e)[:50]),
            ])

        # -----------------------------------------------------------------
        # 3. Tree Logging
        # -----------------------------------------------------------------
        logger.tree("MUTED USER VC VIOLATION", [
            ("User", f"{member} ({member.id})"),
            ("Attempted Channel", channel_name),
            ("Action", "Disconnected + 1h Timeout"),
        ], emoji="🔇")

        # -----------------------------------------------------------------
        # 4. Server Logs - Mutes & Timeouts
        # -----------------------------------------------------------------
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_muted_vc_violation(
                member=member,
                channel_name=channel_name,
                timeout_duration=timeout_duration,
            )

        # -----------------------------------------------------------------
        # 5. Case Log
        # -----------------------------------------------------------------
        if self.bot.case_log_service:
            await self.bot.case_log_service.log_muted_vc_violation(
                user_id=member.id,
                display_name=member.display_name,
                channel_name=channel_name,
                avatar_url=member.display_avatar.url,
            )

    async def _log_mod_voice_activity(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Log voice activity for tracked moderators."""
        if not self.bot.mod_tracker or not self.bot.mod_tracker.is_tracked(member.id):
            return

        # Joined a voice channel
        if before.channel is None and after.channel is not None:
            await self.bot.mod_tracker.log_voice_activity(
                mod=member,
                action="Joined",
                channel=after.channel,
            )

        # Left a voice channel
        elif before.channel is not None and after.channel is None:
            await self.bot.mod_tracker.log_voice_activity(
                mod=member,
                action="Left",
                channel=before.channel,
            )

        # Moved between voice channels
        elif before.channel != after.channel:
            await self.bot.mod_tracker.log_voice_activity(
                mod=member,
                action="Moved",
                from_channel=before.channel,
                to_channel=after.channel,
            )

    async def _log_voice_to_server_logs(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Log voice activity to server logging service."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        if before.channel is None and after.channel is not None:
            await self.bot.logging_service.log_voice_join(member, after.channel)
        elif before.channel is not None and after.channel is None:
            await self.bot.logging_service.log_voice_leave(member, before.channel)
        elif before.channel != after.channel and before.channel and after.channel:
            await self.bot.logging_service.log_voice_move(member, before.channel, after.channel)

        # Stage speaker changes
        if after.channel and isinstance(after.channel, discord.StageChannel):
            # Became a speaker (suppress changed from True to False)
            if before.suppress and not after.suppress:
                await self.bot.logging_service.log_stage_speaker(member, after.channel, True)
            # Stopped being a speaker (suppress changed from False to True)
            elif not before.suppress and after.suppress:
                await self.bot.logging_service.log_stage_speaker(member, after.channel, False)
