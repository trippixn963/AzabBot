"""
Azab Discord Bot - Ban Command Cog
===================================

Server moderation ban/unban commands with case logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger
from src.commands.ban.cog import BanCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the ban cog."""
    await bot.add_cog(BanCog(bot))


__all__ = ["BanCog", "setup"]
