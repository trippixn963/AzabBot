"""
AzabBot - Warn Command Cog
==========================

Warning command implementation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.commands.warn.cog import WarnCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Warn cog."""
    await bot.add_cog(WarnCog(bot))


__all__ = ["WarnCog", "setup"]
