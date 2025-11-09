"""
Azab Discord Bot - Activate Command
==================================

Slash command implementation for activating the bot's ragebaiting mode.
When activated, the bot will monitor messages and respond to muted users
with AI-generated ragebait responses.

Features:
- Enable bot monitoring and responses
- Detect currently muted users
- Update rich presence status
- Persist activation state
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
    
    def __init__(self, bot: Any) -> None:
        """
        Initialize the activate command.
        
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
        @app_commands.command(name="activate", description="Activate ragebaiting mode")
        async def activate(interaction: discord.Interaction) -> None:
            """
            Handle the /activate slash command.
            
            Activates the bot's ragebaiting mode, enabling AI responses
            to muted users. Only administrators can use this command.
            
            Args:
                interaction (discord.Interaction): The Discord interaction object
            """
            if self.bot.is_active:
                await interaction.response.send_message("Bot is already active! Use `/deactivate` first if you want to restart.", ephemeral=True)
                return

            self.bot.is_active = True
            self.bot._save_state()

            await self.bot.presence_handler.update_presence()

            muted_count: int = 0
            if interaction.guild:
                for member in interaction.guild.members:
                    if self.bot.is_user_muted(member):
                        muted_count += 1
                        logger.info(f"Found muted user on activation: {member.name} (ID: {member.id})")

            est: timezone = timezone(timedelta(hours=int(os.getenv('TIMEZONE_OFFSET_HOURS', '-5'))))
            logger.tree("BOT ACTIVATED", [
                ("By", str(interaction.user)),
                ("Time", datetime.now(est).strftime('%I:%M %p EST')),
                ("Status", "Ragebaiting ACTIVE"),
                ("Muted Users Found", str(muted_count))
            ], "🔴")

            embed: discord.Embed = discord.Embed(
                title="🟢 AZAB ACTIVATED",
                description=f"**Ragebaiting Mode Active**\n\nNow monitoring all muted users and generating AI-powered responses.\n\n🔒 **{muted_count} prisoners currently in timeout**",
                color=int(os.getenv('EMBED_COLOR_SUCCESS', '0x00FF00'), 16)
            )

            embed.add_field(name="📊 Status", value="`ACTIVE`", inline=True)
            embed.add_field(name="🎯 Target", value="Muted Users", inline=True)
            embed.add_field(name="🤖 AI Service", value="`ONLINE`" if self.bot.ai.enabled else "`OFFLINE`", inline=True)

            embed.add_field(name="📍 Server", value=interaction.guild.name, inline=True)
            embed.add_field(name="👤 Activated By", value=interaction.user.mention, inline=True)
            embed.add_field(name="🔧 Commands", value="`2 Active`", inline=True)

            embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
            developer: Optional[discord.User] = await self.bot.fetch_user(interaction.user.id)
            developer_avatar: Optional[str] = developer.avatar.url if developer and developer.avatar else None
            embed.set_footer(text=f"Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}", icon_url=developer_avatar)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        return activate