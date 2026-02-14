"""
AzabBot - Quarantine Helpers
============================

Helper functions for the quarantine command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.validation import get_target_guild  # Re-export centralized function
from src.utils.discord_rate_limit import log_http_error

if TYPE_CHECKING:
    from src.bot import AzabBot


async def log_quarantine_action(
    bot: "AzabBot",
    moderator: discord.User,
    guild: discord.Guild,
    action: str,
    reason: Optional[str]) -> None:
    """Log quarantine action to server logs."""
    if not bot.logging_service or not bot.logging_service.enabled:
        return

    try:
        if action == "activate":
            embed = discord.Embed(
                title="🔒 Quarantine Mode Activated",
                description="Server quarantine was manually activated.",
                color=EmbedColors.ERROR
            )
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
            embed.add_field(name="Guild", value=guild.name, inline=True)
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)
        else:
            embed = discord.Embed(
                title="🔓 Quarantine Mode Lifted",
                description="Server quarantine was lifted.",
                color=EmbedColors.SUCCESS
            )
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
            embed.add_field(name="Guild", value=guild.name, inline=True)

        await bot.logging_service._send_log(
            bot.logging_service.LogCategory.MOD_ACTIONS,
            embed)

        logger.debug("Quarantine Action Logged", [
            ("Action", action),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Guild", guild.name),
        ])

    except discord.HTTPException as e:
        log_http_error(e, "Quarantine Log", [
            ("Action", action),
        ])
    except Exception as e:
        logger.error("Quarantine Log Failed", [
            ("Action", action),
            ("Error", str(e)[:100]),
            ("Type", type(e).__name__),
        ])


__all__ = ["get_target_guild", "log_quarantine_action"]
