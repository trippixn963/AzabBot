"""
AzabBot - Quarantine Command Cog
================================

Commands for managing anti-nuke quarantine mode.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.commands.quarantine.cog import QuarantineCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Quarantine cog."""
    await bot.add_cog(QuarantineCog(bot))


__all__ = ["QuarantineCog", "setup"]
