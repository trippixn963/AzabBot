"""
SaydnayaBot - Slash Commands Module
==================================

This module defines all slash commands for the SaydnayaBot as standalone functions
that can be dynamically added to the Discord command tree.

The commands in this module are primarily developer/admin commands that provide
status information and control over the bot's operation. All commands include
proper permission checks to ensure only authorized users can execute them.

Available Commands:
- /activate: Developer command to check bot status
- /deactivate: Developer command that demonstrates bot permanence
"""

import discord
from discord import app_commands

from src.utils.embed_builder import EmbedBuilder


def create_activate_command(bot):
    """
    Create an activate command that shows the bot is always online.
    
    This command is a developer-only command that confirms the bot's active status.
    The bot is designed to be always online and cannot be manually activated.
    
    Args:
        bot: The SaydnayaBot instance that contains the developer_id
        
    Returns:
        The activate command function that can be added to the command tree
    """

    @app_commands.command(
        name="activate", description="Activate the bot (Developer only)"
    )
    async def activate(interaction: discord.Interaction):
        """
        Handle the activate command interaction.
        
        This command confirms that the bot is always active and online.
        Only the bot's developer can use this command.
        """
        # Verify the user is the authorized developer
        if interaction.user.id != bot.developer_id:
            await interaction.response.send_message(
                "❌ Only the developer can use this command.", ephemeral=True
            )
            return
            
        # Confirm bot is always active
        await interaction.response.send_message(
            "✅ Bot is already active and always online!",
            ephemeral=True,
        )

    return activate


def create_deactivate_command(bot):
    """
    Create a deactivate command that demonstrates the bot cannot be deactivated.
    
    This command is a developer-only command that shows the bot's permanence.
    The bot is designed to be always online and cannot be manually deactivated.
    
    Args:
        bot: The SaydnayaBot instance that contains the developer_id
        
    Returns:
        The deactivate command function that can be added to the command tree
    """

    @app_commands.command(
        name="deactivate", description="Deactivate the bot (Developer only)"
    )
    async def deactivate(interaction: discord.Interaction):
        """
        Handle the deactivate command interaction.
        
        This command demonstrates that the bot cannot be deactivated and
        is designed to be always present. Only the bot's developer can use this command.
        """
        # Verify the user is the authorized developer
        if interaction.user.id != bot.developer_id:
            await interaction.response.send_message(
                "❌ Only the developer can use this command.", ephemeral=True
            )
            return
            
        # Demonstrate bot's permanence with a thematic message
        await interaction.response.send_message(
            "⚠️ I cannot be deactivated. I am eternal. I am watching.",
            ephemeral=True,
        )

    return deactivate
