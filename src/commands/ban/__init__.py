"""
AzabBot - Ban Package
=====================

Server moderation ban/unban commands with case logging.

Structure:
    - views.py: BanModal for context menu banning
    - autocomplete.py: Autocomplete functions for reasons and banned users
    - ban_ops.py: Ban execution logic and context menu handlers
    - unban_ops.py: Unban command logic
    - cog.py: Main BanCog class with commands

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .views import BanModal
from .cog import BanCog

if TYPE_CHECKING:
    from src.bot import AzabBot

__all__ = [
    "BanModal",
    "BanCog",
]


async def setup(bot: "AzabBot") -> None:
    """Load the BanCog."""
    await bot.add_cog(BanCog(bot))
    logger.tree("Ban Cog Loaded", [
        ("Commands", "/ban, /unban, context menu"),
        ("Features", "case logging, DM notify"),
    ], emoji="🔨")
