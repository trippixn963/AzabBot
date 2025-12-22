"""
Azab Discord Bot - Embed Footer Utility
========================================

Centralized footer for all embeds.
Avatar is cached and refreshed daily at midnight EST.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import discord
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

FOOTER_TEXT = "trippixn.com/azab"
"""Footer text displayed on all user-facing embeds."""


# =============================================================================
# Module State
# =============================================================================

_cached_avatar_url: Optional[str] = None
"""Cached avatar URL (refreshed daily at midnight EST)."""

_bot_ref: Optional[discord.Client] = None
"""Bot reference for refreshing avatar."""


# =============================================================================
# Helper Functions
# =============================================================================

async def _get_developer_avatar(bot: "AzabBot") -> str:
    """
    Get developer avatar URL for embed footers.

    DESIGN:
        Uses developer's avatar if available, falls back to bot avatar.
        Includes timeout to prevent hanging on API calls.

    Args:
        bot: The bot instance.

    Returns:
        Avatar URL string.
    """
    default_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"

    if bot.user is None:
        return default_avatar

    developer_avatar_url = bot.user.display_avatar.url

    developer_id_str = os.getenv("DEVELOPER_ID")
    if developer_id_str and developer_id_str.isdigit():
        try:
            async with asyncio.timeout(5.0):
                developer = await bot.fetch_user(int(developer_id_str))
                if developer is not None:
                    developer_avatar_url = developer.display_avatar.url
        except (discord.NotFound, discord.HTTPException, asyncio.TimeoutError):
            pass  # Use bot avatar as fallback

    return developer_avatar_url


# =============================================================================
# Initialization
# =============================================================================

async def init_footer(bot: discord.Client) -> None:
    """
    Initialize footer with cached avatar.

    DESIGN:
        Should be called once at bot startup after ready.
        Caches developer avatar to avoid repeated API calls.

    Args:
        bot: The Discord bot client.
    """
    global _bot_ref, _cached_avatar_url
    _bot_ref = bot

    try:
        _cached_avatar_url = await _get_developer_avatar(bot)
        logger.tree("Footer Initialized", [
            ("Text", FOOTER_TEXT),
            ("Avatar Cached", "Yes" if _cached_avatar_url else "No"),
            ("Refresh Schedule", "Daily at 00:00 EST"),
        ], emoji="📝")
    except Exception as e:
        logger.error("Footer Init Failed", [
            ("Error", str(e)),
        ])
        _cached_avatar_url = None


# =============================================================================
# Avatar Refresh
# =============================================================================

async def refresh_avatar() -> None:
    """
    Refresh the cached avatar URL.

    DESIGN:
        Called daily at midnight EST by the scheduler.
        Logs whether avatar changed for debugging.
    """
    global _cached_avatar_url
    if not _bot_ref:
        logger.warning("Footer Avatar Refresh Skipped: Bot reference not set")
        return

    old_url = _cached_avatar_url
    try:
        _cached_avatar_url = await _get_developer_avatar(_bot_ref)
        changed = old_url != _cached_avatar_url
        logger.tree("Footer Avatar Refreshed", [
            ("Changed", "Yes" if changed else "No"),
        ], emoji="🔄")
    except Exception as e:
        logger.error("Footer Avatar Refresh Failed", [
            ("Error", str(e)),
        ])


# =============================================================================
# Footer Setter
# =============================================================================

def set_footer(embed: discord.Embed, avatar_url: Optional[str] = None) -> discord.Embed:
    """
    Set the standard footer on an embed.

    DESIGN:
        Uses cached avatar URL by default.
        Allows override for special cases.

    Args:
        embed: The embed to add footer to.
        avatar_url: Optional override avatar URL (uses cached if not provided).

    Returns:
        The embed with footer set.
    """
    url = avatar_url if avatar_url is not None else _cached_avatar_url
    embed.set_footer(text=FOOTER_TEXT, icon_url=url)
    return embed


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "FOOTER_TEXT",
    "init_footer",
    "refresh_avatar",
    "set_footer",
]
