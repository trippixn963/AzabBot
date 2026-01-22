"""
AzabBot - Channels Handler
==========================

Handles channel and role management logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class ChannelLogsMixin:
    """Mixin for channel and role management logging."""

    async def log_channel_create(
        self: "LoggingService",
        channel: discord.abc.GuildChannel,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a channel creation."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📁 Channel Created", EmbedColors.SUCCESS, category="Channel Create")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_channel_delete(
        self: "LoggingService",
        channel_name: str,
        channel_type: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log a channel deletion."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📁 Channel Deleted", EmbedColors.LOG_NEGATIVE, category="Channel Delete")
        channel_value = f"<#{channel_id}> · `{channel_name}`" if channel_id else f"`{channel_name}`"
        embed.add_field(name="Channel", value=channel_value, inline=True)
        embed.add_field(name="Type", value=channel_type.title(), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_channel_update(
        self: "LoggingService",
        channel: discord.abc.GuildChannel,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a channel update."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📁 Channel Updated", EmbedColors.WARNING, category="Channel Update")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_role_create(
        self: "LoggingService",
        role: discord.Role,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role creation."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🎭 Role Created", EmbedColors.SUCCESS, category="Role Create")
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.ROLES, embed)

    async def log_role_delete(
        self: "LoggingService",
        role_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role deletion."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🎭 Role Deleted", EmbedColors.LOG_NEGATIVE, category="Role Delete")
        role_display = f"`{role_name}`" if role_name else "unknown role"
        embed.add_field(name="Role", value=role_display, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.ROLES, embed)

    async def log_role_update(
        self: "LoggingService",
        role: discord.Role,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role update."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🎭 Role Updated", EmbedColors.WARNING, category="Role Update")
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.ROLES, embed)

    async def log_permission_update(
        self: "LoggingService",
        channel: discord.abc.GuildChannel,
        target: str,
        action: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log permission overwrite changes."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed(f"🔐 Permission {action.title()}", EmbedColors.WARNING, category=f"Permission {action.title()}")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        embed.add_field(name="Target", value=f"`{target}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.PERMISSIONS, embed)
