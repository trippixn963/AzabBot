# =============================================================================
# SaydnayaBot - Slash Commands Module
# =============================================================================
# Defines all slash commands for the bot as standalone functions that can be
# added to the command tree.
# =============================================================================

import discord
from discord import app_commands

from src.utils.embed_builder import EmbedBuilder


def create_activate_command(bot):
    """Create an activate command (bot is always online)."""

    @app_commands.command(
        name="activate", description="Activate the bot (Developer only)"
    )
    async def activate(interaction: discord.Interaction):
        """Bot is always online."""
        # Check if user is developer
        if interaction.user.id != bot.developer_id:
            await interaction.response.send_message(
                "❌ Only the developer can use this command.", ephemeral=True
            )
            return
            
        await interaction.response.send_message(
            "✅ Bot is already active and always online!",
            ephemeral=True,
        )

    return activate


def create_deactivate_command(bot):
    """Create a deactivate command (bot cannot be deactivated)."""

    @app_commands.command(
        name="deactivate", description="Deactivate the bot (Developer only)"
    )
    async def deactivate(interaction: discord.Interaction):
        """Bot cannot be deactivated."""
        # Check if user is developer
        if interaction.user.id != bot.developer_id:
            await interaction.response.send_message(
                "❌ Only the developer can use this command.", ephemeral=True
            )
            return
            
        await interaction.response.send_message(
            "⚠️ I cannot be deactivated. I am eternal. I am watching.",
            ephemeral=True,
        )

    return deactivate
