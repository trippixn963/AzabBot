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
from datetime import timezone
import pytz

from src import __version__
from src.utils.embed_builder import EmbedBuilder
from src.utils.time_utils import get_est_time


def create_activate_command(bot):
    """
    Create an activate command that activates the bot.
    
    This command is restricted to authorized users (developer and specific moderators)
    and activates the bot's monitoring.
    
    Args:
        bot: The AzabBot instance that contains the developer_id
        
    Returns:
        The activate command function that can be added to the command tree
    """

    @app_commands.command(
        name="activate", description="Enable bot responses (Authorized users only)"
    )
    async def activate(interaction: discord.Interaction):
        """
        Handle the activate command interaction.
        
        This command activates the bot's monitoring and response system.
        Only authorized users (developer and specific moderators) can use this command.
        """
        # List of authorized user IDs (developer + moderators from config)
        authorized_users = [bot.developer_id]
        # Add moderator IDs from config if available
        moderator_ids = bot.config.get("MODERATOR_IDS", [])
        if moderator_ids:
            authorized_users.extend(moderator_ids)
        
        # Verify the user is authorized
        if interaction.user.id not in authorized_users:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only authorized users can use this command.",
                color=0xFF0000,
                timestamp=get_est_time()
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Respond to interaction immediately to avoid timeout
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
        embed.set_footer(text="Developed by حَـــــنَّـــــا")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Now activate the bot and do background tasks
        bot.is_active = True
        bot.logger.log_info("✅ Bot activated by developer command")
        
        # Update bot presence to show active status
        activity = discord.Activity(
            type=discord.ActivityType.watching, name="⛓ Sednaya"
        )
        await bot.change_presence(activity=activity, status=discord.Status.online)
        
        # Start background tasks asynchronously
        import asyncio
        async def activate_tasks():
            # Scan for current prisoners if not already done
            await bot._scan_for_prisoners()
            
            # Process recent messages from prisoners
            await bot._process_recent_prisoner_messages()
            
            # Start presence rotation task if not already running
            if bot.presence_rotation_task:
                bot.presence_rotation_task.cancel()
            bot.presence_rotation_task = bot.loop.create_task(bot._rotate_presence())
        
        # Run activation tasks in background
        bot.loop.create_task(activate_tasks())

    return activate


def create_deactivate_command(bot):
    """
    Create a deactivate command that deactivates the bot.
    
    This command is restricted to authorized users (developer and specific moderators)
    and deactivates the bot's monitoring.
    
    Args:
        bot: The AzabBot instance that contains the developer_id
        
    Returns:
        The deactivate command function that can be added to the command tree
    """

    @app_commands.command(
        name="deactivate", description="Disable bot responses (Authorized users only)"
    )
    async def deactivate(interaction: discord.Interaction):
        """
        Handle the deactivate command interaction.
        
        This command deactivates the bot's monitoring and response system.
        Only authorized users (developer and specific moderators) can use this command.
        """
        # List of authorized user IDs (developer + moderators from config)
        authorized_users = [bot.developer_id]
        # Add moderator IDs from config if available
        moderator_ids = bot.config.get("MODERATOR_IDS", [])
        if moderator_ids:
            authorized_users.extend(moderator_ids)
        
        # Verify the user is authorized
        if interaction.user.id not in authorized_users:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only authorized users can use this command.",
                color=0xFF0000,
                timestamp=get_est_time()
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Deactivate the bot
        bot.is_active = False
        bot.logger.log_info("🔴 Bot deactivated by developer command")
        
        # Update bot presence to show inactive status
        activity = discord.Activity(
            type=discord.ActivityType.watching, name="💤 Inactive"
        )
        await bot.change_presence(activity=activity, status=discord.Status.idle)
        
        # Stop presence rotation task
        if bot.presence_rotation_task:
            bot.presence_rotation_task.cancel()
            bot.presence_rotation_task = None
        
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
        embed.set_footer(text="Developed by حَـــــنَّـــــا")
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
                timestamp=get_est_time()
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
                    timestamp=get_est_time()
                )
                if bot.user and bot.user.avatar:
                    embed.set_thumbnail(url=bot.user.avatar.url)
                embed.set_footer(text="Developed by حَـــــنَّـــــا")
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                embed = discord.Embed(
                    title="❌ Health Report Failed",
                    description="Failed to send health report. Check webhook configuration and logs for details.",
                    color=0xFF0000,
                    timestamp=get_est_time()
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
                timestamp=get_est_time()
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            embed.add_field(name="Configuration", value="Set HEALTH_WEBHOOK_URL in your .env file", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    return health
