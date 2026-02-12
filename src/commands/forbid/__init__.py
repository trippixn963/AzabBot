"""
AzabBot - Forbid Package
========================

Restrict specific permissions for users without fully muting them.

Structure:
    - constants.py: Restriction types and configuration
    - views.py: UI views and modals for forbid appeals
    - cog.py: Main ForbidCog class
    - roles.py: Role management mixin
    - scheduler.py: Background task mixin
    - dm.py: DM notification mixin

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .constants import RESTRICTIONS, FORBID_ROLE_PREFIX
from .views import (
    ForbidAppealButton,
    ForbidAppealView,
    ForbidAppealModal,
    setup_forbid_views,
)
from .cog import ForbidCog

if TYPE_CHECKING:
    from src.bot import AzabBot

__all__ = [
    "RESTRICTIONS",
    "FORBID_ROLE_PREFIX",
    "ForbidAppealButton",
    "ForbidAppealView",
    "ForbidAppealModal",
    "setup_forbid_views",
    "ForbidCog",
]


async def setup(bot: "AzabBot") -> None:
    """Load the ForbidCog."""
    await bot.add_cog(ForbidCog(bot))
    logger.tree("Forbid Cog Loaded", [
        ("Commands", "/forbid, /unforbid"),
        ("Features", "permission restrictions, appeals"),
    ], emoji="🚫")
