"""
Azab Discord Bot - Snipe Command Cog
=====================================

View deleted and edited messages in a channel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.commands.snipe.cog import SnipeCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Snipe cog."""
    await bot.add_cog(SnipeCog(bot))


__all__ = ["SnipeCog", "setup"]
