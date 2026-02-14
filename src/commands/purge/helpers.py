"""
AzabBot - Purge Helpers
=======================

Helper functions for the purge command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ

if TYPE_CHECKING:
    from src.bot import AzabBot


async def log_purge_usage(
    bot: "AzabBot",
    interaction: discord.Interaction,
    channel: discord.abc.GuildChannel,
    deleted_count: int,
    purge_type: str,
    old_deleted: int,
    failed_count: int,
    reason: Optional[str]) -> None:
    """Log purge usage to server logs."""
    if not bot.logging_service or not bot.logging_service.enabled:
        return

    try:
        embed = discord.Embed(
            title="🗑️ Messages Purged",
            color=EmbedColors.WARNING
        )

        embed.add_field(
            name="Moderator",
            value=f"{interaction.user.mention}\n`{interaction.user.id}`",
            inline=True)
        embed.add_field(
            name="Channel",
            value=f"{channel.mention}\n`{channel.id}`",
            inline=True)
        embed.add_field(
            name="Deleted",
            value=f"`{deleted_count}` messages",
            inline=True)
        embed.add_field(
            name="Type",
            value=f"`{purge_type}`",
            inline=True)

        if old_deleted > 0:
            embed.add_field(
                name="Old (14d+)",
                value=f"`{old_deleted}` (individual)",
                inline=True)

        if failed_count > 0:
            embed.add_field(
                name="Failed",
                value=f"`{failed_count}` messages",
                inline=True)

        if reason:
            embed.add_field(
                name="Reason",
                value=reason,
                inline=False)

        await bot.logging_service._send_log(
            bot.logging_service.LogCategory.MOD_ACTIONS,
            embed)

    except Exception as e:
        logger.debug("Purge Log Failed", [("Error", str(e)[:50])])


__all__ = ["log_purge_usage"]
