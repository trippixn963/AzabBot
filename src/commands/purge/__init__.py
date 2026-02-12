"""
AzabBot - Purge Command Package
===============================

Bulk message deletion command for channel moderation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .cog import PurgeCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Purge cog."""
    await bot.add_cog(PurgeCog(bot))
    logger.tree("Purge Cog Loaded", [
        ("Commands", "/purge"),
        ("Features", "bulk message deletion"),
    ], emoji="🧹")


__all__ = ["PurgeCog", "setup"]
