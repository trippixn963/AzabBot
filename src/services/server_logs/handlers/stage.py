"""
Server Logs - Stage Handler
===========================

Handles stage instance logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class StageLogsMixin:
    """Mixin for stage instance logging."""

    async def log_stage_start(
        self: "LoggingService",
        stage: discord.StageInstance,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a stage instance starting."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🎤 Stage Started", EmbedColors.SUCCESS, category="Stage Start")
        embed.add_field(name="Topic", value=f"`{stage.topic}`", inline=True)

        if stage.channel:
            embed.add_field(name="Channel", value=self._format_channel(stage.channel), inline=True)

        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.STAGE, embed)

    async def log_stage_end(
        self: "LoggingService",
        channel_name: str,
        topic: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log a stage instance ending."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🎤 Stage Ended", EmbedColors.LOG_NEGATIVE, category="Stage End")
        embed.add_field(name="Topic", value=f"`{topic}`", inline=True)
        channel_value = f"🔊 <#{channel_id}>" if channel_id else f"🔊 `{channel_name}`"
        embed.add_field(name="Channel", value=channel_value, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.STAGE, embed)

    async def log_stage_update(
        self: "LoggingService",
        stage: discord.StageInstance,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a stage instance being updated."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🎤 Stage Updated", EmbedColors.WARNING, category="Stage Update")
        embed.add_field(name="Topic", value=f"`{stage.topic}`", inline=True)
        if stage.channel:
            embed.add_field(name="Channel", value=self._format_channel(stage.channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.STAGE, embed)

    async def log_stage_speaker(
        self: "LoggingService",
        member: discord.Member,
        channel: discord.StageChannel,
        became_speaker: bool,
    ) -> None:
        """Log a member becoming/stopping being a speaker."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        if became_speaker:
            embed = self._create_embed("🎤 Speaker Added", EmbedColors.SUCCESS, category="Speaker Add", user_id=member.id)
        else:
            embed = self._create_embed("🎤 Speaker Removed", EmbedColors.WARNING, category="Speaker Remove", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Stage", value=self._format_channel(channel), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.STAGE, embed, user_id=member.id)


__all__ = ["StageLogsMixin"]
