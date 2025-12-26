"""
Azab Discord Bot - Banner Utility
==================================

Syncs bot banner with server banner.
Banner is cached and refreshed daily at midnight EST.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import aiohttp
import discord
from typing import Optional

from src.core.logger import logger
from src.core.config import get_config


# Cached banner bytes
_cached_banner: Optional[bytes] = None

# Bot reference for refreshing banner
_bot_ref: Optional[discord.Client] = None


async def init_banner(bot: discord.Client) -> None:
    """
    Initialize bot banner from server banner.
    Should be called once at bot startup after ready.
    """
    global _bot_ref
    _bot_ref = bot

    await refresh_banner()


async def refresh_banner() -> None:
    """
    Refresh the bot's banner from the server banner.
    Called daily at midnight EST by the scheduler.
    """
    global _cached_banner

    if not _bot_ref:
        logger.warning("Banner Refresh Skipped", [
            ("Reason", "Bot reference not set"),
        ])
        return

    config = get_config()
    guild_id = config.logging_guild_id

    if not guild_id:
        logger.info("Banner Refresh Skipped", [
            ("Reason", "No guild ID configured"),
        ])
        return

    try:
        # Get the main guild
        guild = _bot_ref.get_guild(guild_id)
        if not guild:
            logger.warning("Banner Refresh Skipped", [
                ("Reason", "Guild not found"),
                ("Guild ID", str(guild_id)),
            ])
            return

        # Check if guild has a banner
        if not guild.banner:
            logger.info("Banner Refresh Skipped", [
                ("Reason", "Server has no banner"),
            ])
            return

        # Get banner URL (use high quality)
        banner_url = guild.banner.url

        # Download banner
        async with aiohttp.ClientSession() as session:
            async with session.get(banner_url) as response:
                if response.status != 200:
                    logger.warning("Banner Download Failed", [
                        ("Status", str(response.status)),
                    ])
                    return

                new_banner = await response.read()

        # Check if banner changed
        if new_banner == _cached_banner:
            logger.info("Banner Unchanged", [
                ("Action", "Skipping update"),
            ])
            return

        # Update bot banner
        await _bot_ref.user.edit(banner=new_banner)
        _cached_banner = new_banner

        logger.success("Bot Banner Updated", [
            ("Source", guild.name),
            ("Size", f"{len(new_banner) / 1024:.1f} KB"),
        ])

    except discord.HTTPException as e:
        if e.code == 50035:  # Invalid image or bot doesn't have nitro
            logger.info("Banner Update Skipped", [
                ("Reason", "Bot cannot set banner (requires Nitro)"),
            ])
        else:
            logger.error("Banner Update Failed", [
                ("Error", str(e)),
            ])
    except Exception as e:
        logger.error("Banner Refresh Failed", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)),
        ])


__all__ = [
    "init_banner",
    "refresh_banner",
]
