"""
Server Logs - AutoMod Handler
=============================

Handles AutoMod action logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class AutoModLogsMixin:
    """Mixin for AutoMod action logging."""

    async def log_automod_action(
        self: "LoggingService",
        rule_name: str,
        action_type: str,
        user: discord.Member,
        channel: Optional[discord.abc.GuildChannel] = None,
        content: Optional[str] = None,
        matched_keyword: Optional[str] = None,
    ) -> None:
        """Log an AutoMod action."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🛡️ AutoMod Action", EmbedColors.WARNING, category="AutoMod", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Rule", value=f"`{rule_name}`", inline=True)
        embed.add_field(name="Action", value=f"`{action_type}`", inline=True)

        if channel:
            embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        if matched_keyword:
            embed.add_field(name="Matched", value=f"`{matched_keyword}`", inline=True)

        if content:
            truncated = content[:300] if len(content) > 300 else content
            embed.add_field(name="Content", value=f"```{truncated}```", inline=False)

        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.AUTOMOD, embed, user_id=user.id)

    async def log_automod_block(
        self: "LoggingService",
        rule_name: str,
        user: discord.Member,
        channel: Optional[discord.abc.GuildChannel] = None,
        content: Optional[str] = None,
        matched_keyword: Optional[str] = None,
    ) -> None:
        """Log a message blocked by AutoMod."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🛡️ Message Blocked", EmbedColors.LOG_NEGATIVE, category="AutoMod Block", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Rule", value=f"`{rule_name}`", inline=True)

        if channel:
            embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        if matched_keyword:
            embed.add_field(name="Matched", value=f"`{matched_keyword}`", inline=True)

        if content:
            truncated = content[:300] if len(content) > 300 else content
            embed.add_field(name="Content", value=f"```{truncated}```", inline=False)

        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.AUTOMOD, embed, user_id=user.id)


__all__ = ["AutoModLogsMixin"]
