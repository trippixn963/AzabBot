"""
AzabBot - Snipe Helpers Mixin
=============================

Server logging helper methods for snipe commands.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ

if TYPE_CHECKING:
    from .cog import SnipeCog


class HelpersMixin:
    """Mixin for snipe logging helpers."""

    async def _log_snipe_usage(
        self: "SnipeCog",
        interaction: discord.Interaction,
        target_id: int,
        target_name: str,
        message_number: int,
        content_preview: str,
        filter_user: Optional[discord.User] = None) -> None:
        """Log snipe usage to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🎯 Snipe Used",
                color=EmbedColors.GOLD
            )

            embed.add_field(
                name="Moderator",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True)
            embed.add_field(
                name="Target",
                value=f"{target_name}\n`{target_id}`",
                inline=True)
            embed.add_field(
                name="Channel",
                value=f"{interaction.channel.mention}" if interaction.channel else "Unknown",
                inline=True)
            embed.add_field(
                name="Message #",
                value=f"`{message_number}`",
                inline=True)
            if filter_user:
                embed.add_field(
                    name="Filter",
                    value=f"{filter_user.mention}\n`{filter_user.id}`",
                    inline=True)
            embed.add_field(
                name="Content Preview",
                value=f"```{content_preview[:100]}```" if content_preview else "*(empty)*",
                inline=False)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed)

        except Exception as e:
            logger.debug("Snipe Log Failed", [("Error", str(e)[:50])])

    async def _log_editsnipe_usage(
        self: "SnipeCog",
        interaction: discord.Interaction,
        target_id: int,
        target_name: str,
        message_number: int,
        before_preview: str,
        after_preview: str,
        filter_user: Optional[discord.User] = None) -> None:
        """Log editsnipe usage to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="✏️ Editsnipe Used",
                color=EmbedColors.GOLD
            )

            embed.add_field(
                name="Moderator",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True)
            embed.add_field(
                name="Target",
                value=f"{target_name}\n`{target_id}`",
                inline=True)
            embed.add_field(
                name="Channel",
                value=f"{interaction.channel.mention}" if interaction.channel else "Unknown",
                inline=True)
            embed.add_field(
                name="Message #",
                value=f"`{message_number}`",
                inline=True)
            if filter_user:
                embed.add_field(
                    name="Filter",
                    value=f"{filter_user.mention}\n`{filter_user.id}`",
                    inline=True)
            embed.add_field(
                name="Before",
                value=f"```{before_preview[:100]}```" if before_preview else "*(empty)*",
                inline=False)
            embed.add_field(
                name="After",
                value=f"```{after_preview[:100]}```" if after_preview else "*(empty)*",
                inline=False)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed)

        except Exception as e:
            logger.debug("Editsnipe Log Failed", [("Error", str(e)[:50])])

    async def _log_clearsnipe_usage(
        self: "SnipeCog",
        interaction: discord.Interaction,
        target: Optional[discord.User],
        cleared_deleted: int,
        cleared_edits: int) -> None:
        """Log clearsnipe usage to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🧹 Snipe Cache Cleared",
                color=EmbedColors.WARNING
            )

            embed.add_field(
                name="Moderator",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True)

            if target:
                embed.add_field(
                    name="Target User",
                    value=f"{target.mention}\n`{target.id}`",
                    inline=True)
            else:
                embed.add_field(
                    name="Target",
                    value="All messages",
                    inline=True)

            embed.add_field(
                name="Channel",
                value=f"{interaction.channel.mention}" if interaction.channel else "Unknown",
                inline=True)
            embed.add_field(
                name="Deleted",
                value=f"`{cleared_deleted}` message(s)",
                inline=True)
            embed.add_field(
                name="Edits",
                value=f"`{cleared_edits}` message(s)",
                inline=True)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed)

        except Exception as e:
            logger.debug("Clearsnipe Log Failed", [("Error", str(e)[:50])])


__all__ = ["HelpersMixin"]
