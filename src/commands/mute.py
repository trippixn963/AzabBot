"""
AzabBot - Mute Command Cog
==========================

Role-based mute/unmute commands with timed auto-unmute.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.commands.mute.cog import MuteCog, mute_author_context, unmute_author_context
from src.core.logger import logger
from src.utils.duration import parse_duration, format_duration

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Cog Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the mute cog and context menus."""
    await bot.add_cog(MuteCog(bot))
    bot.tree.add_command(mute_author_context)
    bot.tree.add_command(unmute_author_context)

    logger.tree("Mute Context Menus Registered", [
        ("Mute Author", "Message context menu"),
        ("Unmute Author", "Message context menu"),
    ], emoji="🔇")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["MuteCog", "setup", "parse_duration", "format_duration"]
