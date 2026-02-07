"""
AzabBot - Purge Command Package
===============================

Bulk message deletion command for channel moderation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from .cog import PurgeCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Purge cog."""
    await bot.add_cog(PurgeCog(bot))


__all__ = ["PurgeCog", "setup"]
