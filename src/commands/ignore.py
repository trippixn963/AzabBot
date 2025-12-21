"""
Azab Discord Bot - Ignore Command Cog
======================================

Slash command for ignoring/unignoring specific users.

DESIGN:
    Allows developers to prevent the bot from responding to specific users.
    Ignored users are stored in the database and persist across restarts.
    The developer cannot be ignored to prevent lockout scenarios.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, is_developer, EmbedColors

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Ignore Cog
# =============================================================================

class IgnoreCog(commands.Cog):
    """
    Commands for managing ignored users.

    DESIGN:
        Developer-only command for blocking problem users.
        Uses database for persistence across restarts.
        Prevents ignoring the developer or the bot itself.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the ignore cog.

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
    # Ignore Command
    # =========================================================================

    @app_commands.command(name="ignore", description="Ignore or unignore a specific user")
    @app_commands.describe(
        action="Choose to ignore or unignore the user",
        user="The user to ignore or unignore",
    )
    async def ignore(
        self,
        interaction: discord.Interaction,
        action: Literal["ignore", "unignore"],
        user: discord.User,
    ) -> None:
        """
        Manage the bot's ignore list.

        DESIGN:
            Validates target before modifying ignore list.
            Logs all changes with tree format for visibility.
            Shows confirmation embed with user details.

        Args:
            interaction: Discord interaction context.
            action: Whether to ignore or unignore.
            user: Target user to modify.
        """
        await interaction.response.defer(ephemeral=True)

        # -------------------------------------------------------------------------
        # Validate Target
        # -------------------------------------------------------------------------

        # Prevent ignoring the bot itself
        if self.bot.user and user.id == self.bot.user.id:
            await interaction.followup.send(
                "I cannot ignore myself!",
                ephemeral=True,
            )
            return

        # Prevent ignoring the developer
        if is_developer(user.id):
            await interaction.followup.send(
                "I cannot ignore the developer!",
                ephemeral=True,
            )
            return

        # -------------------------------------------------------------------------
        # Handle Ignore Action
        # -------------------------------------------------------------------------

        if action == "ignore":
            if self.bot.db.is_user_ignored(user.id):
                await interaction.followup.send(
                    f"**{user.name}** is already being ignored.",
                    ephemeral=True,
                )
                return

            self.bot.db.add_ignored_user(user.id)

            embed = discord.Embed(
                title="User Ignored",
                description="The bot will now ignore all messages from this user.",
                color=EmbedColors.ERROR,
            )

            embed.add_field(name="User", value=user.mention, inline=True)
            embed.add_field(name="User ID", value=str(user.id), inline=True)
            embed.add_field(name="Action", value="Ignored", inline=True)

            embed.set_thumbnail(
                url=user.avatar.url if user.avatar else user.default_avatar.url
            )
            embed.set_footer(
                text=f"Executed by {interaction.user.name} | Developed By: {self.config.developer_name}"
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

            logger.tree("USER IGNORED", [
                ("User", str(user)),
                ("User ID", str(user.id)),
                ("By", str(interaction.user)),
                ("By ID", str(interaction.user.id)),
            ], emoji="🔇")

        # -------------------------------------------------------------------------
        # Handle Unignore Action
        # -------------------------------------------------------------------------

        elif action == "unignore":
            if not self.bot.db.is_user_ignored(user.id):
                await interaction.followup.send(
                    f"**{user.name}** is not currently being ignored.",
                    ephemeral=True,
                )
                return

            self.bot.db.remove_ignored_user(user.id)

            embed = discord.Embed(
                title="User Unignored",
                description="The bot will now respond to this user again.",
                color=EmbedColors.SUCCESS,
            )

            embed.add_field(name="User", value=user.mention, inline=True)
            embed.add_field(name="User ID", value=str(user.id), inline=True)
            embed.add_field(name="Action", value="Unignored", inline=True)

            embed.set_thumbnail(
                url=user.avatar.url if user.avatar else user.default_avatar.url
            )
            embed.set_footer(
                text=f"Executed by {interaction.user.name} | Developed By: {self.config.developer_name}"
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

            logger.tree("USER UNIGNORED", [
                ("User", str(user)),
                ("User ID", str(user.id)),
                ("By", str(interaction.user)),
                ("By ID", str(interaction.user.id)),
            ], emoji="🔊")


# =============================================================================
# Cog Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """
    Load the ignore cog.

    Args:
        bot: Main bot instance.
    """
    await bot.add_cog(IgnoreCog(bot))


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["IgnoreCog", "setup"]
