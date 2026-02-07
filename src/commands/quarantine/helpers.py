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
from src.utils.footer import set_footer
from src.utils.discord_rate_limit import log_http_error

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.core.config import Config


def get_target_guild(
    interaction: discord.Interaction,
    bot: "AzabBot",
    config: "Config",
) -> Optional[discord.Guild]:
    """Get the target guild for quarantine (supports cross-server moderation)."""
    if (config.mod_server_id and
        config.logging_guild_id and
        interaction.guild and
        interaction.guild.id == config.mod_server_id):
        main_guild = bot.get_guild(config.logging_guild_id)
        if main_guild:
            return main_guild
    return interaction.guild


async def log_quarantine_action(
    bot: "AzabBot",
    moderator: discord.User,
    guild: discord.Guild,
    action: str,
    reason: Optional[str],
) -> None:
    """Log quarantine action to server logs."""
    if not bot.logging_service or not bot.logging_service.enabled:
        return

    try:
        if action == "activate":
            embed = discord.Embed(
                title="🔒 Quarantine Mode Activated",
                description="Server quarantine was manually activated.",
                color=EmbedColors.ERROR,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
            embed.add_field(name="Guild", value=guild.name, inline=True)
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)
        else:
            embed = discord.Embed(
                title="🔓 Quarantine Mode Lifted",
                description="Server quarantine was lifted.",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
            embed.add_field(name="Guild", value=guild.name, inline=True)

        set_footer(embed)

        await bot.logging_service._send_log(
            bot.logging_service.LogCategory.MOD_ACTIONS,
            embed,
        )

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
