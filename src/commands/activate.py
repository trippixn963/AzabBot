"""
Azab Discord Bot - Activate Command
==================================

Slash command implementation for activating the bot's ragebaiting mode.
When activated, the bot will monitor messages and respond to muted users
with AI-generated ragebait responses.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: Modular
"""

import discord
from discord import app_commands
from datetime import datetime

from src.core.logger import logger


class ActivateCommand:
    """
    Discord slash command for activating bot's ragebaiting mode.
    
    This command enables the bot to:
    - Monitor all incoming messages
    - Detect muted/timed out users
    - Generate AI responses to muted users
    - Log all interactions for analytics
    
    Requires administrator permissions to execute.
    """
    
    def __init__(self, bot):
        """
        Initialize the activate command.
        
        Args:
            bot: The main AzabBot instance
        """
        self.bot = bot
    
    def create_command(self):
        """
        Create and return the Discord slash command.
        
        Returns:
            discord.app_commands.Command: The configured slash command
        """
        @app_commands.command(name="activate", description="Activate ragebaiting mode")
        @app_commands.default_permissions(administrator=True)
        async def activate(interaction: discord.Interaction):
            """
            Handle the /activate slash command.
            
            Activates the bot's ragebaiting mode, enabling AI responses
            to muted users. Only administrators can use this command.
            
            Args:
                interaction (discord.Interaction): The Discord interaction object
            """
            # Check if bot is already active (bot starts as active by default)
            if self.bot.is_active:
                # Create warning embed for already active state
                embed = discord.Embed(
                    title="⚠️ Already Active",
                    description="Bot is already active!\n\nUse `/deactivate` first if you want to restart.",
                    color=0xFFAA00  # Orange/warning color
                )
                embed.set_footer(text="Developed By: حَـــــنَّـــــا")
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Activate bot's ragebaiting mode
            self.bot.is_active = True
            
            # Check for currently muted users (both timeout and role)
            muted_count = 0
            if interaction.guild:
                for member in interaction.guild.members:
                    if self.bot.is_user_muted(member):
                        muted_count += 1
                        # Count muted users
            
            # Log activation event
            logger.activation_change(True, str(interaction.user), muted_count)
            logger.command_used("activate", str(interaction.user), interaction.guild.name)
            
            # Create activation confirmation embed
            embed = discord.Embed(
                title="🟢 AZAB ACTIVATED",
                description=f"**Ragebaiting Mode Active**\n\nNow monitoring all muted users and generating AI-powered responses.\n\n🔒 **{muted_count} prisoners currently in timeout**",
                color=0x00FF00
            )
            
            # Add detailed status fields
            embed.add_field(name="📊 Status", value="`ACTIVE`", inline=True)
            embed.add_field(name="🎯 Target", value="Muted Users", inline=True)
            embed.add_field(name="🤖 AI Service", value="`ONLINE`" if self.bot.ai.enabled else "`OFFLINE`", inline=True)
            
            # Add server info
            embed.add_field(name="📍 Server", value=interaction.guild.name, inline=True)
            embed.add_field(name="👤 Activated By", value=interaction.user.mention, inline=True)
            embed.add_field(name="🔧 Commands", value="`2 Active`", inline=True)
            
            embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
            # Use developer's profile picture for footer branding
            embed.set_footer(
                text="Developed by حَـــــنَّـــــا",
                icon_url="https://cdn.discordapp.com/avatars/1404020045876690985/a_1234567890abcdef1234567890abcdef.webp"
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        return activate