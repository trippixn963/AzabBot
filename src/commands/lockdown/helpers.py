"""
AzabBot - Lockdown Helpers
==========================

Helper functions for the lockdown command.

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
    """
    Get the target guild for lockdown (supports cross-server moderation).

    If in mod server and main guild is configured, target main guild.

    Args:
        interaction: The Discord interaction.
        bot: The bot instance.
        config: The bot configuration.

    Returns:
        Target guild or None if not found.
    """
    if (config.mod_server_id and
        config.logging_guild_id and
        interaction.guild and
        interaction.guild.id == config.mod_server_id):
        main_guild = bot.get_guild(config.logging_guild_id)
        if main_guild:
            logger.debug("Cross-Server Lockdown", [
                ("From", f"{interaction.guild.name} ({interaction.guild.id})"),
                ("Target", f"{main_guild.name} ({main_guild.id})"),
            ])
            return main_guild
    return interaction.guild


async def send_public_announcement(
    guild: discord.Guild,
    action: str,
    config: "Config",
) -> bool:
    """
    Send public announcement to general channel.

    Args:
        guild: The guild.
        action: "lock" or "unlock".
        config: The bot configuration.

    Returns:
        True if sent successfully.
    """
    if not config.general_channel_id:
        return False

    channel = guild.get_channel(config.general_channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        logger.debug("General Channel Not Found", [
            ("Channel ID", str(config.general_channel_id)),
        ])
        return False

    try:
        if action == "lock":
            embed = discord.Embed(
                title="🔒 Server Locked",
                description="This server is currently in **lockdown mode**.\nPlease stand by while moderators handle the situation.",
                color=EmbedColors.ERROR,
                timestamp=datetime.now(NY_TZ),
            )
        else:
            embed = discord.Embed(
                title="🔓 Server Unlocked",
                description="The lockdown has been lifted.\nYou may now resume normal activity.",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )

        set_footer(embed)
        await channel.send(embed=embed)

        logger.debug("Public Announcement Sent", [
            ("Channel", f"#{channel.name}"),
            ("Action", action),
        ])
        return True

    except discord.Forbidden:
        logger.warning("Announcement Failed", [
            ("Channel", f"#{channel.name} ({channel.id})"),
            ("Error", "Missing permissions"),
        ])
        return False

    except discord.HTTPException as e:
        log_http_error(e, "Announcement", [
            ("Channel", f"#{channel.name} ({channel.id})"),
        ])
        return False


__all__ = ["get_target_guild", "send_public_announcement"]
