"""
AzabBot - Warn Command Package
==============================

Server moderation warning command with case logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from .cog import WarnCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Warn cog."""
    await bot.add_cog(WarnCog(bot))


__all__ = ["WarnCog", "setup"]
