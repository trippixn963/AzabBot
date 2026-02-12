"""
AzabBot - Snipe Package
=======================

View deleted and edited messages in a channel.

Structure:
    - helpers.py: Server logging helper methods
    - snipe_cmd.py: /snipe command implementation
    - editsnipe_cmd.py: /editsnipe command implementation
    - clearsnipe_cmd.py: /clearsnipe command implementation
    - cog.py: Main SnipeCog class

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .cog import SnipeCog

if TYPE_CHECKING:
    from src.bot import AzabBot

__all__ = ["SnipeCog"]


async def setup(bot: "AzabBot") -> None:
    """Load the SnipeCog."""
    await bot.add_cog(SnipeCog(bot))
    logger.tree("Snipe Cog Loaded", [
        ("Commands", "/snipe, /editsnipe, /clearsnipe"),
        ("Features", "deleted/edited message recovery"),
    ], emoji="🎯")
