"""
AzabBot - Quarantine Command Package
====================================

Commands for managing anti-nuke quarantine mode.

When activated, quarantine strips all dangerous permissions from roles,
effectively locking down the server at a role level (vs channel level
like /lockdown).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from .cog import QuarantineCog

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Quarantine cog."""
    await bot.add_cog(QuarantineCog(bot))


__all__ = ["QuarantineCog", "setup"]
