"""
AzabBot - Cog
=============

Main MuteCog class with commands.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role
from src.core.database import get_db
from src.core.moderation_validation import (
    validate_evidence,
    get_target_guild,
    is_cross_server,
)

# Import mixins
from .helpers import HelpersMixin
from .autocomplete import AutocompleteMixin
from .mute_ops import MuteOpsMixin
from .unmute_ops import UnmuteOpsMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class MuteCog(HelpersMixin, AutocompleteMixin, MuteOpsMixin, UnmuteOpsMixin, commands.Cog):
    """
    Moderation commands for muting and unmuting users.

    DESIGN:
        Uses role-based muting for more control than Discord timeouts.
        Stores mute records in database for persistence across restarts.
        Integrates with mute scheduler for automatic unmutes.
        Supports cross-server moderation from mod server to main server.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the mute cog.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("Mute Cog Loaded", [
            ("Commands", "/mute, /unmute"),
            ("Context Menus", "Mute Author, Unmute Author"),
            ("Cross-Server", "Enabled"),
        ], emoji="🔇")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """
        Check if user has permission to use mute commands.

        DESIGN:
            Uses role-based permission check (has_mod_role).
            Allows developers, admins, moderator IDs, and moderation role.

        Args:
            interaction: Discord interaction to check.

        Returns:
            True if user has permission.
        """
        return has_mod_role(interaction.user)

    # =========================================================================
    # Mute Command
    # =========================================================================

    @app_commands.command(name="mute", description="Mute a user by assigning the muted role")
    @app_commands.describe(
        user="The user to mute",
        duration="How long to mute (e.g., 10m, 1h, 1d, permanent)",
        reason="Reason for the mute (required)",
        evidence="Screenshot or video evidence (image/video only)",
    )
    @app_commands.autocomplete(duration=AutocompleteMixin.duration_autocomplete, reason=AutocompleteMixin.reason_autocomplete)
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        duration: str,
        reason: str,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Mute a user by assigning the muted role (supports cross-server from mod server)."""
        # Validate evidence attachment (content type, file size, CDN expiry warning)
        evidence_result = validate_evidence(evidence, "mute")
        if not evidence_result.is_valid:
            await interaction.response.send_message(
                evidence_result.error_message,
                ephemeral=True,
            )
            return

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=False)
        except discord.HTTPException:
            pass  # Interaction already responded or expired
        await self.execute_mute(interaction, user, duration, reason, evidence_result.url)

    # =========================================================================
    # Unmute Command
    # =========================================================================

    @app_commands.command(name="unmute", description="Unmute a user by removing the muted role")
    @app_commands.describe(
        user="The user to unmute",
        reason="Reason for the unmute",
    )
    @app_commands.autocomplete(reason=AutocompleteMixin.removal_reason_autocomplete)
    async def unmute(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Unmute a user by removing the muted role (supports cross-server from mod server)."""
        # Pre-validate before deferring (so errors can be ephemeral)
        target_guild = get_target_guild(interaction, self.bot)
        target_member = target_guild.get_member(user.id)

        if not target_member:
            guild_name = target_guild.name if is_cross_server(interaction) else "this server"
            await interaction.response.send_message(
                f"User is not a member of {guild_name}.",
                ephemeral=True,
            )
            return

        muted_role = target_guild.get_role(self.config.muted_role_id)
        if not muted_role:
            await interaction.response.send_message(
                f"Muted role not found (ID: {self.config.muted_role_id}).",
                ephemeral=True,
            )
            return

        if muted_role not in target_member.roles:
            await interaction.response.send_message(
                f"**{target_member.display_name}** is not muted.",
                ephemeral=True,
            )
            return

        # All validation passed - now defer and execute
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=False)
        except discord.HTTPException:
            pass  # Interaction already responded or expired
        await self.execute_unmute(interaction, user, reason, skip_validation=True)


# =============================================================================
# Context Menu Commands
# =============================================================================

@app_commands.context_menu(name="Mute Author")
async def mute_author_context(interaction: discord.Interaction, message: discord.Message) -> None:
    """
    Context menu command to mute the author of a message.

    DESIGN:
        Right-click a message -> Apps -> Mute Author
        Opens modal with duration/reason, auto-fills evidence with message link.
    """
    if not has_mod_role(interaction.user):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True,
        )
        return

    cog = interaction.client.get_cog("MuteCog")
    if cog:
        await cog._mute_from_message(interaction, message)
    else:
        await interaction.response.send_message(
            "Mute command not available.",
            ephemeral=True,
        )


@app_commands.context_menu(name="Unmute Author")
async def unmute_author_context(interaction: discord.Interaction, message: discord.Message) -> None:
    """
    Context menu command to unmute the author of a message.

    DESIGN:
        Right-click a message -> Apps -> Unmute Author
        Immediately unmutes if user is muted.
    """
    if not has_mod_role(interaction.user):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True,
        )
        return

    cog = interaction.client.get_cog("MuteCog")
    if cog:
        await cog._unmute_from_message(interaction, message)
    else:
        await interaction.response.send_message(
            "Unmute command not available.",
            ephemeral=True,
        )


__all__ = ["MuteCog", "mute_author_context", "unmute_author_context"]
