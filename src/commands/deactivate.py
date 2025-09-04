"""
Azab Discord Bot - Deactivate Command
====================================

Slash command implementation for deactivating the bot's ragebaiting mode.
When deactivated, the bot returns to standby state and stops monitoring
messages for AI responses.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: Modular
"""

import discord
from discord import app_commands
from datetime import datetime

from src.core.logger import logger


class DeactivateCommand:
    """
    Discord slash command for deactivating bot's ragebaiting mode.
    
    This command disables the bot's ability to:
    - Monitor incoming messages
    - Generate AI responses to muted users
    - Process message interactions
    
    Bot returns to standby state but remains connected to Discord.
    Requires administrator permissions to execute.
    """
    
    def __init__(self, bot):
        """
        Initialize the deactivate command.
        
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
        @app_commands.command(name="deactivate", description="Deactivate ragebaiting mode")
        @app_commands.default_permissions(administrator=True)
        async def deactivate(interaction: discord.Interaction):
            """
            Handle the /deactivate slash command.
            
            Deactivates the bot's ragebaiting mode, returning it to
            standby state. Only administrators can use this command.
            
            Args:
                interaction (discord.Interaction): The Discord interaction object
            """
            # Check if bot is already inactive
            if not self.bot.is_active:
                # Create warning embed for already inactive state
                embed = discord.Embed(
                    title="⚠️ Already Inactive",
                    description="Bot is already inactive!\n\nUse `/activate` to start ragebaiting mode.",
                    color=0xFFAA00  # Orange/warning color
                )
                embed.set_footer(text="Developed By: حَـــــنَّـــــا")
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Deactivate bot's ragebaiting mode
            self.bot.is_active = False
            
            # Log deactivation event
            logger.activation_change(False, str(interaction.user))
            logger.command_used("deactivate", str(interaction.user), interaction.guild.name)
            
            # Create deactivation confirmation embed
            embed = discord.Embed(
                title="🔴 AZAB DEACTIVATED",
                description="**Ragebaiting Mode Disabled**\n\nBot is now in standby mode. Use `/activate` to resume operations.",
                color=0xFF0000
            )
            
            # Add detailed status fields
            embed.add_field(name="📊 Status", value="`INACTIVE`", inline=True)
            embed.add_field(name="🎯 Target", value="None", inline=True)
            embed.add_field(name="🤖 AI Service", value="`STANDBY`", inline=True)
            
            # Add server info
            embed.add_field(name="📍 Server", value=interaction.guild.name, inline=True)
            embed.add_field(name="👤 Deactivated By", value=interaction.user.mention, inline=True)
            embed.add_field(name="⏱️ Mode", value="Sleeping", inline=True)
            
            embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
            # Use developer's profile picture for footer branding
            embed.set_footer(
                text="Developed by حَـــــنَّـــــا",
                icon_url="https://cdn.discordapp.com/avatars/1404020045876690985/a_1234567890abcdef1234567890abcdef.webp"
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        return deactivate