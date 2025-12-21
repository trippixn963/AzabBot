"""
Azab Discord Bot - Toggle Commands Cog
=======================================

Slash commands for activating/deactivating the bot's ragebaiting mode.

DESIGN:
    These commands allow developers to toggle the bot's active state.
    When deactivated, the bot ignores muted users and shows idle presence.
    State is persisted to database for consistency across restarts.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, is_developer, EmbedColors

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Toggle Cog
# =============================================================================

class ToggleCog(commands.Cog):
    """
    Commands for toggling bot activation state.

    DESIGN:
        Developer-only commands for controlling bot behavior.
        Updates both runtime state and database persistence.
        Syncs presence handler to reflect new state.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the toggle cog.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """
        Only developers can use these commands.

        Args:
            interaction: Discord interaction to check.

        Returns:
            True if user is the developer.
        """
        return is_developer(interaction.user.id)

    # =========================================================================
    # Activate Command
    # =========================================================================

    @app_commands.command(name="activate", description="Activate ragebaiting mode")
    async def activate(self, interaction: discord.Interaction) -> None:
        """
        Enable the bot's monitoring and response system.

        DESIGN:
            Activates bot, persists state, updates presence.
            Shows count of currently muted users for context.
        """
        if not self.bot.disabled:
            await interaction.response.send_message(
                "Bot is already active! Use `/deactivate` first.",
                ephemeral=True,
            )
            return

        # -------------------------------------------------------------------------
        # Activate Bot
        # -------------------------------------------------------------------------

        self.bot.disabled = False
        self.bot.db.set_active(True)

        # -------------------------------------------------------------------------
        # Update Presence
        # -------------------------------------------------------------------------

        if self.bot.presence_handler:
            await self.bot.presence_handler.update_presence()

        # -------------------------------------------------------------------------
        # Count Muted Users
        # -------------------------------------------------------------------------

        muted_count = 0
        if interaction.guild:
            for member in interaction.guild.members:
                if self.bot.is_user_muted(member):
                    muted_count += 1

        logger.tree("BOT ACTIVATED", [
            ("By", str(interaction.user)),
            ("User ID", str(interaction.user.id)),
            ("Muted Users", str(muted_count)),
        ], emoji="🔴")

        # -------------------------------------------------------------------------
        # Build Response Embed
        # -------------------------------------------------------------------------

        embed = discord.Embed(
            title="AZAB ACTIVATED",
            description=(
                f"**Ragebaiting Mode Active**\n\n"
                f"Now monitoring all muted users.\n\n"
                f"**{muted_count}** prisoners currently in timeout"
            ),
            color=EmbedColors.SUCCESS,
        )

        embed.add_field(name="Status", value="`ACTIVE`", inline=True)
        embed.add_field(name="Target", value="Muted Users", inline=True)
        embed.add_field(
            name="AI Service",
            value="`ONLINE`" if self.bot.ai_service else "`OFFLINE`",
            inline=True,
        )

        if self.bot.user and self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.set_footer(text=f"Developed By: {self.config.developer_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # =========================================================================
    # Deactivate Command
    # =========================================================================

    @app_commands.command(name="deactivate", description="Deactivate ragebaiting mode")
    async def deactivate(self, interaction: discord.Interaction) -> None:
        """
        Disable the bot's monitoring and response system.

        DESIGN:
            Deactivates bot, persists state, updates presence to idle.
            Bot will ignore all muted user messages until reactivated.
        """
        if self.bot.disabled:
            await interaction.response.send_message(
                "Already inactive!",
                ephemeral=True,
            )
            return

        # -------------------------------------------------------------------------
        # Deactivate Bot
        # -------------------------------------------------------------------------

        self.bot.disabled = True
        self.bot.db.set_active(False)

        # -------------------------------------------------------------------------
        # Update Presence
        # -------------------------------------------------------------------------

        if self.bot.presence_handler:
            await self.bot.presence_handler.update_presence()

        logger.tree("BOT DEACTIVATED", [
            ("By", str(interaction.user)),
            ("User ID", str(interaction.user.id)),
        ], emoji="💤")

        # -------------------------------------------------------------------------
        # Build Response Embed
        # -------------------------------------------------------------------------

        embed = discord.Embed(
            title="AZAB DEACTIVATED",
            description=(
                "**Ragebaiting Mode Disabled**\n\n"
                "Bot is now in standby mode. Use `/activate` to resume."
            ),
            color=EmbedColors.ERROR,
        )

        embed.add_field(name="Status", value="`INACTIVE`", inline=True)
        embed.add_field(name="Mode", value="Sleeping", inline=True)

        if self.bot.user and self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.set_footer(text=f"Developed By: {self.config.developer_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


# =============================================================================
# Cog Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """
    Load the toggle cog.

    Args:
        bot: Main bot instance.
    """
    await bot.add_cog(ToggleCog(bot))


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ToggleCog", "setup"]
