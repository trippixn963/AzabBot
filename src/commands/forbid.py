"""
AzabBot - Forbid Command Cog
============================

Restrict specific permissions for users without fully muting them.

This is a thin wrapper that imports from the forbid package.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.commands.forbid.cog import ForbidCog
from src.commands.forbid.views import setup_forbid_views
from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Forbid cog."""
    setup_forbid_views(bot)
    await bot.add_cog(ForbidCog(bot))

    logger.tree("Forbid Views Registered", [
        ("Dynamic Items", "Permission request buttons"),
    ], emoji="🚫")


__all__ = ["ForbidCog", "setup"]
