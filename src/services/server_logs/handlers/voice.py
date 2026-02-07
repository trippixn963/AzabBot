"""
AzabBot - Voice Handler
=======================

Handles voice channel activity logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors, has_mod_role
from ..categories import LogCategory

if TYPE_CHECKING:
    from ..service import LoggingService


class VoiceLogsMixin:
    """Mixin for voice activity logging."""

    async def log_voice_join(
        self: "LoggingService",
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        """Log a voice channel join."""
        if not self._should_log(member.guild.id, member.id):
            return

        if has_mod_role(member):
            return

        embed = self._create_embed("🟢 Voice Join", EmbedColors.SUCCESS, category="Voice Join", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=f"🔊 {self._format_channel(channel)}", inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_leave(
        self: "LoggingService",
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        """Log a voice channel leave."""
        if not self._should_log(member.guild.id, member.id):
            return

        if has_mod_role(member):
            return

        embed = self._create_embed("🔴 Voice Leave", EmbedColors.LOG_NEGATIVE, category="Voice Leave", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=f"🔊 {self._format_channel(channel)}", inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_move(
        self: "LoggingService",
        member: discord.Member,
        before: discord.VoiceChannel,
        after: discord.VoiceChannel,
    ) -> None:
        """Log a voice channel move."""
        if not self._should_log(member.guild.id):
            return

        if has_mod_role(member):
            return

        embed = self._create_embed("🔀 Voice Move", EmbedColors.BLUE, category="Voice Move", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Moved", value=f"{before.name} → {after.name}", inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_mute(
        self: "LoggingService",
        member: discord.Member,
        muted: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a server mute/unmute."""
        if not self._should_log(member.guild.id):
            return

        if muted:
            embed = self._create_embed("🔇 Server Muted", EmbedColors.WARNING, category="Voice Mute", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Server Unmuted", EmbedColors.SUCCESS, category="Voice Unmute", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_deafen(
        self: "LoggingService",
        member: discord.Member,
        deafened: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a server deafen/undeafen."""
        if not self._should_log(member.guild.id):
            return

        if deafened:
            embed = self._create_embed("🔇 Server Deafened", EmbedColors.WARNING, category="Voice Deafen", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Server Undeafened", EmbedColors.SUCCESS, category="Voice Undeafen", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_self_mute(
        self: "LoggingService",
        member: discord.Member,
        channel: discord.VoiceChannel,
        muted: bool,
    ) -> None:
        """Log a user self-muting/unmuting."""
        if not self._should_log(member.guild.id, member.id):
            return

        if has_mod_role(member):
            return

        if muted:
            embed = self._create_embed("🔇 Self Muted", EmbedColors.INFO, category="Self Mute", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Self Unmuted", EmbedColors.INFO, category="Self Unmute", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_self_deafen(
        self: "LoggingService",
        member: discord.Member,
        channel: discord.VoiceChannel,
        deafened: bool,
    ) -> None:
        """Log a user self-deafening/undeafening."""
        if not self._should_log(member.guild.id, member.id):
            return

        if has_mod_role(member):
            return

        if deafened:
            embed = self._create_embed("🔇 Self Deafened", EmbedColors.INFO, category="Self Deafen", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Self Undeafened", EmbedColors.INFO, category="Self Undeafen", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_stream(
        self: "LoggingService",
        member: discord.Member,
        channel: discord.VoiceChannel,
        streaming: bool,
    ) -> None:
        """Log a user starting/stopping a stream."""
        if not self._should_log(member.guild.id, member.id):
            return

        if streaming:
            embed = self._create_embed("📺 Started Streaming", EmbedColors.SUCCESS, category="Stream Start", user_id=member.id)
        else:
            embed = self._create_embed("📺 Stopped Streaming", EmbedColors.WARNING, category="Stream Stop", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_video(
        self: "LoggingService",
        member: discord.Member,
        channel: discord.VoiceChannel,
        video_on: bool,
    ) -> None:
        """Log a user turning camera on/off."""
        if not self._should_log(member.guild.id, member.id):
            return

        if video_on:
            embed = self._create_embed("📹 Camera On", EmbedColors.SUCCESS, category="Camera On", user_id=member.id)
        else:
            embed = self._create_embed("📹 Camera Off", EmbedColors.WARNING, category="Camera Off", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)
