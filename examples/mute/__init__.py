"""
AzabBot - Mute Package
======================

Role-based mute/unmute commands with timed auto-unmute.

Structure:
    - constants.py: Duration choices for autocomplete
    - views.py: MuteModal for context menu muting
    - helpers.py: DM and logging helper methods
    - autocomplete.py: Autocomplete handlers
    - mute_ops.py: Mute execution logic
    - unmute_ops.py: Unmute execution logic
    - cog.py: Main MuteCog class

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .constants import DURATION_CHOICES
from .views import MuteModal
from .cog import MuteCog, mute_author_context, unmute_author_context

if TYPE_CHECKING:
    from src.bot import AzabBot

__all__ = [
    "DURATION_CHOICES",
    "MuteModal",
    "MuteCog",
    "mute_author_context",
    "unmute_author_context",
]


async def setup(bot: "AzabBot") -> None:
    """Load the MuteCog."""
    await bot.add_cog(MuteCog(bot))
    logger.tree("Mute Cog Loaded", [
        ("Commands", "/mute, /unmute, context menu"),
        ("Features", "timed mutes, DM notify"),
    ], emoji="🔇")
