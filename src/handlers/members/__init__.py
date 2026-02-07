"""
AzabBot - Member Events Package
===============================

Handles member join, leave, and update events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .cog import MemberEvents

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Add the member events cog to the bot."""
    await bot.add_cog(MemberEvents(bot))
    logger.tree("Member Events Loaded", [
        ("Events", "join, leave, update, ban, unban"),
        ("Features", "mute detection, mod tracking, gender roles"),
    ], emoji="👤")


__all__ = ["MemberEvents", "setup"]
