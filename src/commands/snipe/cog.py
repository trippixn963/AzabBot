"""
AzabBot - Snipe Cog
===================

Main SnipeCog class combining all command mixins.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role
from src.core.database import get_db
from src.core.constants import SNIPE_MAX_AGE

from .helpers import HelpersMixin
from .snipe_cmd import SnipeCmdMixin
from .editsnipe_cmd import EditsnipeCmdMixin
from .clearsnipe_cmd import ClearsnipeCmdMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class SnipeCog(HelpersMixin, SnipeCmdMixin, EditsnipeCmdMixin, ClearsnipeCmdMixin, commands.Cog):
    """Cog for sniping deleted and edited messages."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("Snipe Cog Loaded", [
            ("Commands", "/snipe, /editsnipe, /clearsnipe"),
            ("Deleted Storage", "Database (persists)"),
            ("Edited Storage", "Memory (session)"),
            ("Max Age", f"{SNIPE_MAX_AGE}s"),
        ], emoji="🎯")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use snipe commands."""
        return has_mod_role(interaction.user)


__all__ = ["SnipeCog"]
