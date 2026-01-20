"""
Azab Discord Bot - Message Events
=================================

Handles message create, delete, and edit events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger
from src.events.messages.cog import MessageEvents

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Add the message events cog to the bot."""
    await bot.add_cog(MessageEvents(bot))
    logger.debug("Message Events Loaded")


__all__ = ["MessageEvents", "setup"]
