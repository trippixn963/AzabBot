"""
AzabBot - Message Events Package
================================

Handles message create, delete, and edit events.

Structure:
    - helpers.py: Helper methods for prisoner ping, invite handling, partnership
    - cog.py: Main MessageEvents cog with event listeners

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .cog import MessageEvents

if TYPE_CHECKING:
    from src.bot import AzabBot

__all__ = ["MessageEvents"]


async def setup(bot: "AzabBot") -> None:
    """Load the MessageEvents cog."""
    await bot.add_cog(MessageEvents(bot))
    logger.tree("Message Events Loaded", [
        ("Events", "on_message, delete, edit"),
        ("Features", "snipe, invite filter, antispam"),
    ], emoji="💬")
