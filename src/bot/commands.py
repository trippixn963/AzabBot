# =============================================================================
# SaydnayaBot - Slash Commands Module
# =============================================================================
# Defines all slash commands for the bot as standalone functions that can be
# added to the command tree.
# =============================================================================

import random
import discord
from discord import app_commands
from src.utils.embed_builder import EmbedBuilder
from src.core.logger import log_system_event


def create_activate_command(bot):
    """Create a status command (activation no longer needed - bot is always online)."""
    @app_commands.command(name="activate", description="Bot is always online - use /status instead")
    async def activate(interaction: discord.Interaction):
        """Bot is always online."""
        await interaction.response.send_message(
            "ℹ️ Bot is always online! Use `/status` to check current status.", 
            ephemeral=True
        )
    
    return activate


def create_deactivate_command(bot):
    """Create a deactivate command (no longer functional - bot is always online)."""
    @app_commands.command(name="deactivate", description="Bot is always online - cannot be deactivated")
    async def deactivate(interaction: discord.Interaction):
        """Bot cannot be deactivated."""
        await interaction.response.send_message(
            "⚠️ Bot is always online and cannot be deactivated! Use `/status` to check current status.",
            ephemeral=True
        )
    
    return deactivate


def create_status_command(bot):
    """Create the status slash command."""
    @app_commands.command(name="status", description="Check bot status (Developer only)")
    async def status(interaction: discord.Interaction):
        """Check the current status of the bot."""
        # Defer the response immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        # Check if user is developer
        if interaction.user.id != bot.developer_id:
            await interaction.followup.send(
                "❌ Only the developer can use this command.", ephemeral=True
            )
            return
            
        # Create status embed
        # Set the developer icon in embed builder if available
        if interaction.user.avatar:
            EmbedBuilder.DEVELOPER_ICON = interaction.user.avatar.url
        
        embed = EmbedBuilder.create_status_embed(
            status="Active",  # Always active
            stats={
                "prisoners": len(bot.current_prisoners) if hasattr(bot, 'current_prisoners') else 0,
                "messages": bot.metrics.messages_seen,
                "responses": bot.metrics.responses_generated,
            },
            bot_avatar_url=bot.user.avatar.url if bot.user.avatar else None,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    return status