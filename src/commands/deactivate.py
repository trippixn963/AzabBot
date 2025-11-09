"""
Azab Discord Bot - Deactivate Command
====================================

Slash command implementation for deactivating the bot's ragebaiting mode.
When deactivated, the bot returns to standby state and stops monitoring
messages for AI responses.

Features:
- Disable bot monitoring and responses
- Update rich presence to sleeping status
- Persist deactivation state
- Family members can still interact
- Administrator-only access

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta
import os
from typing import Any, Optional

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
    
    def __init__(self, bot: Any) -> None:
        """
        Initialize the deactivate command.
        
        Args:
            bot: The main AzabBot instance
        """
        self.bot: Any = bot
    
    def create_command(self) -> app_commands.Command:
        """
        Create and return the Discord slash command.
        
        Returns:
            discord.app_commands.Command: The configured slash command
        """
        @app_commands.command(name="deactivate", description="Deactivate ragebaiting mode")
        async def deactivate(interaction: discord.Interaction) -> None:
            """
            Handle the /deactivate slash command.
            
            Deactivates the bot's ragebaiting mode, returning it to
            standby state. Only administrators can use this command.
            
            Args:
                interaction (discord.Interaction): The Discord interaction object
            """
            if not self.bot.is_active:
                await interaction.response.send_message("Already inactive!", ephemeral=True)
                return

            self.bot.is_active = False
            self.bot._save_state()

            await self.bot.presence_handler.update_presence()

            est: timezone = timezone(timedelta(hours=int(os.getenv('TIMEZONE_OFFSET_HOURS', '-5'))))
            logger.tree("BOT DEACTIVATED", [
                ("By", str(interaction.user)),
                ("Time", datetime.now(est).strftime('%I:%M %p EST')),
                ("Status", "Sleeping")
            ], "💤")

            embed: discord.Embed = discord.Embed(
                title="🔴 AZAB DEACTIVATED",
                description="**Ragebaiting Mode Disabled**\n\nBot is now in standby mode. Use `/activate` to resume operations.",
                color=int(os.getenv('EMBED_COLOR_ERROR', '0xFF0000'), 16)
            )

            embed.add_field(name="📊 Status", value="`INACTIVE`", inline=True)
            embed.add_field(name="🎯 Target", value="None", inline=True)
            embed.add_field(name="🤖 AI Service", value="`STANDBY`", inline=True)

            embed.add_field(name="📍 Server", value=interaction.guild.name, inline=True)
            embed.add_field(name="👤 Deactivated By", value=interaction.user.mention, inline=True)
            embed.add_field(name="⏱️ Mode", value="Sleeping", inline=True)

            embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
            developer: Optional[discord.User] = await self.bot.fetch_user(interaction.user.id)
            developer_avatar: Optional[str] = developer.avatar.url if developer and developer.avatar else None
            embed.set_footer(text=f"Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}", icon_url=developer_avatar)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        return deactivate