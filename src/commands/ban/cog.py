"""
Azab Discord Bot - Ban Cog
==========================

Main BanCog class with command definitions.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role
from src.core.moderation_validation import validate_evidence

from .autocomplete import reason_autocomplete
from .ban_ops import BanOpsMixin
from .unban_ops import UnbanOpsMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class BanCog(BanOpsMixin, UnbanOpsMixin, commands.Cog):
    """Ban/unban command implementations."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

        # Register context menus
        self.ban_user_ctx = app_commands.ContextMenu(
            name="Ban User",
            callback=self._ban_from_user,
        )
        self.ban_message_ctx = app_commands.ContextMenu(
            name="Ban Author",
            callback=self._ban_from_message,
        )
        self.bot.tree.add_command(self.ban_user_ctx)
        self.bot.tree.add_command(self.ban_message_ctx)

        logger.tree("Ban Cog Loaded", [
            ("Commands", "/ban, /unban, /massban"),
            ("Context Menus", "Ban User, Ban Author"),
            ("Cross-Server", "Enabled"),
        ], emoji="🔨")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use ban commands."""
        return has_mod_role(interaction.user)

    async def cog_unload(self) -> None:
        """Remove context menus when cog unloads."""
        self.bot.tree.remove_command(self.ban_user_ctx.name, type=self.ban_user_ctx.type)
        self.bot.tree.remove_command(self.ban_message_ctx.name, type=self.ban_message_ctx.type)

    # =========================================================================
    # /ban Command
    # =========================================================================

    @app_commands.command(name="ban", description="Ban a user from the server")
    @app_commands.describe(
        user="The user to ban",
        reason="Reason for the ban (required)",
        evidence="Screenshot or video evidence (image/video only)",
    )
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Ban a user from the server (supports cross-server from mod server)."""
        # Validate evidence attachment (content type, file size, CDN expiry warning)
        evidence_result = validate_evidence(evidence, "ban")
        if not evidence_result.is_valid:
            await interaction.response.send_message(
                evidence_result.error_message,
                ephemeral=True,
            )
            return

        await self.execute_ban(
            interaction=interaction,
            user=user,
            reason=reason,
            evidence=evidence_result.url,
        )


__all__ = ["BanCog"]
