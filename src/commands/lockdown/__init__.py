"""
AzabBot - Lockdown Command Package
==================================

Emergency server lockdown command for raid protection.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .cog import LockdownCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Lockdown cog."""
    await bot.add_cog(LockdownCog(bot))


__all__ = ["LockdownCog", "setup"]
