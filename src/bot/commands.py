"""
AzabBot - Slash Commands Module
==================================

This module defines all slash commands for the AzabBot as standalone functions
that can be dynamically added to the Discord command tree.

The commands in this module are primarily developer/admin commands that provide
status information and control over the bot's operation. All commands include
proper permission checks to ensure only authorized users can execute them.

Available Commands:
- /activate: Developer command to check bot status
- /deactivate: Developer command that demonstrates bot permanence
- /health: Developer command to manually trigger health report
"""

import discord
from discord import app_commands

from src.utils.embed_builder import EmbedBuilder


def create_activate_command(bot):
    """
    Create an activate command that activates the bot.
    
    This command is a developer-only command that activates the bot's monitoring.
    
    Args:
        bot: The AzabBot instance that contains the developer_id
        
    Returns:
        The activate command function that can be added to the command tree
    """

    @app_commands.command(
        name="activate", description="Enable bot responses (Developer only)"
    )
    async def activate(interaction: discord.Interaction):
        """
        Handle the activate command interaction.
        
        This command activates the bot's monitoring and response system.
        Only the bot's developer can use this command.
        """
        # Verify the user is the authorized developer
        if interaction.user.id != bot.developer_id:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only the developer can use this command.",
                color=0xFF0000,
                timestamp=discord.utils.utcnow()
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Activate the bot
        bot.is_active = True
        bot.logger.log_info("✅ Bot activated by developer command")
        
        # Create success embed
        embed = discord.Embed(
            title="✅ Bot Activated",
            description="AzabBot is now active and will respond to prisoners!",
            color=0x00FF00,
            timestamp=discord.utils.utcnow()
        )
        if bot.user and bot.user.avatar:
            embed.set_thumbnail(url=bot.user.avatar.url)
        embed.add_field(name="Status", value="🟢 Active", inline=True)
        embed.add_field(name="Responses", value="💬 Enabled", inline=True)
        embed.add_field(name="Prisoners", value=f"{len(bot.current_prisoners)}", inline=True)
        embed.set_footer(text="AzabBot v1.5.0 • Responding")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    return activate


def create_deactivate_command(bot):
    """
    Create a deactivate command that deactivates the bot.
    
    This command is a developer-only command that deactivates the bot's monitoring.
    
    Args:
        bot: The AzabBot instance that contains the developer_id
        
    Returns:
        The deactivate command function that can be added to the command tree
    """

    @app_commands.command(
        name="deactivate", description="Disable bot responses (Developer only)"
    )
    async def deactivate(interaction: discord.Interaction):
        """
        Handle the deactivate command interaction.
        
        This command deactivates the bot's monitoring and response system.
        Only the bot's developer can use this command.
        """
        # Verify the user is the authorized developer
        if interaction.user.id != bot.developer_id:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only the developer can use this command.",
                color=0xFF0000,
                timestamp=discord.utils.utcnow()
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Deactivate the bot
        bot.is_active = False
        bot.logger.log_info("🔴 Bot deactivated by developer command")
        
        # Create deactivation embed
        embed = discord.Embed(
            title="🔴 Bot Deactivated",
            description="AzabBot is now inactive. Still learning but not responding.",
            color=0xFF0000,
            timestamp=discord.utils.utcnow()
        )
        if bot.user and bot.user.avatar:
            embed.set_thumbnail(url=bot.user.avatar.url)
        embed.add_field(name="Status", value="⭕ Inactive", inline=True)
        embed.add_field(name="Responses", value="🔇 Disabled", inline=True)
        embed.add_field(name="Commands", value="✅ Still Available", inline=True)
        embed.set_footer(text="AzabBot v1.5.0 • Silent Mode")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    return deactivate


def create_health_command(bot):
    """
    Create a health check command to manually trigger health report.
    
    This command allows the developer to manually trigger a health status
    report to be sent via webhook, useful for testing or immediate status checks.
    
    Args:
        bot: The AzabBot instance
        
    Returns:
        The health command function
    """
    
    @app_commands.command(
        name="health", description="Send health status report (Developer only)"
    )
    async def health(interaction: discord.Interaction):
        """
        Handle the health command interaction.
        
        Triggers an immediate health status report via webhook.
        """
        # Verify the user is the authorized developer
        if interaction.user.id != bot.developer_id:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only the developer can use this command.",
                color=0xFF0000,
                timestamp=discord.utils.utcnow()
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Defer response since health check might take a moment
        await interaction.response.defer(ephemeral=True)
        
        # Trigger health check
        if hasattr(bot, 'webhook_health') and bot.webhook_health:
            success = await bot.webhook_health.send_health_report(force=True)
            if success:
                embed = discord.Embed(
                    title="✅ Health Report Sent",
                    description="Health status report has been sent to the webhook successfully!",
                    color=0x00FF00,
                    timestamp=discord.utils.utcnow()
                )
                if bot.user and bot.user.avatar:
                    embed.set_thumbnail(url=bot.user.avatar.url)
                embed.set_footer(text="AzabBot Health Monitor v1.5.0")
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                embed = discord.Embed(
                    title="❌ Health Report Failed",
                    description="Failed to send health report. Check webhook configuration and logs for details.",
                    color=0xFF0000,
                    timestamp=discord.utils.utcnow()
                )
                if bot.user and bot.user.avatar:
                    embed.set_thumbnail(url=bot.user.avatar.url)
                embed.add_field(name="Troubleshooting", value="• Check HEALTH_WEBHOOK_URL in .env\n• Verify webhook is valid\n• Check logs for error details", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="⚠️ Service Not Configured",
                description="Health webhook service is not configured or initialized.",
                color=0xFFFF00,
                timestamp=discord.utils.utcnow()
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            embed.add_field(name="Configuration", value="Set HEALTH_WEBHOOK_URL in your .env file", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    return health
