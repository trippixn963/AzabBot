"""
AzabBot - Channel Events Package
================================

Handles channel, thread, role, emoji, sticker, invite, voice,
reaction, stage, scheduled event, and automod events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .cog import ChannelEvents

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Add the channel events cog to the bot."""
    await bot.add_cog(ChannelEvents(bot))
    logger.tree("Channel Events Loaded", [
        ("Events", "channel, thread, role, emoji, invite"),
        ("Features", "voice, reaction, stage, automod"),
    ], emoji="📺")


__all__ = ["ChannelEvents", "setup"]
