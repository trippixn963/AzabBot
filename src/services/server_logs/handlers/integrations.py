"""
AzabBot - Integrations Handler
==============================

Handles webhook and integration logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class IntegrationsLogsMixin:
    """Mixin for integration and webhook logging."""

    async def log_integration_add(
        self: "LoggingService",
        name: str,
        int_type: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an integration being added."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🔗 Integration Added", EmbedColors.INFO, category="Integration Add")
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Type", value=int_type, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    async def log_integration_remove(
        self: "LoggingService",
        name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an integration being removed."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🔗 Integration Removed", EmbedColors.LOG_NEGATIVE, category="Integration Remove")
        embed.add_field(name="Name", value=name, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    async def log_webhook_create(
        self: "LoggingService",
        webhook_name: str,
        channel: discord.abc.GuildChannel,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a webhook being created."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🪝 Webhook Created", EmbedColors.SUCCESS, category="Webhook Create")
        embed.add_field(name="Name", value=f"`{webhook_name}`", inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    async def log_webhook_delete(
        self: "LoggingService",
        webhook_name: str,
        channel_name: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log a webhook being deleted."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🪝 Webhook Deleted", EmbedColors.LOG_NEGATIVE, category="Webhook Delete")
        embed.add_field(name="Name", value=f"`{webhook_name}`", inline=True)
        channel_value = f"<#{channel_id}>" if channel_id else f"`{channel_name}`"
        embed.add_field(name="Channel", value=channel_value, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)


__all__ = ["IntegrationsLogsMixin"]
