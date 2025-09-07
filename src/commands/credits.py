"""
Azab Discord Bot - Credits Command
==================================

Public slash command showing bot credits, information, and statistics.
Displays developer info, tech stack, features, and GitHub repository.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.2.0
"""

import discord
from discord import app_commands
from discord.ui import Button, View
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.core.logger import logger
from src.utils.version import Version


class CreditsCommand:
    """
    Discord slash command for displaying bot credits and information.
    
    This is a public command that anyone can use to learn about:
    - Bot developer and creation details
    - Technical specifications and features
    - GitHub repository and version
    - Server statistics
    
    No permissions required - accessible to all users.
    """
    
    def __init__(self, bot: Any) -> None:
        """
        Initialize the credits command.
        
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
        @app_commands.command(name="credits", description="View bot credits and information")
        async def credits(interaction: discord.Interaction) -> None:
            """
            Handle the /credits slash command.
            
            Displays comprehensive information about the bot including
            developer credits, features, tech stack, and statistics.
            
            Args:
                interaction (discord.Interaction): The Discord interaction object
            """
            try:
                # Fetch developer info using Discord API
                developer: Optional[discord.User] = await self.bot.fetch_user(self.bot.developer_id)
                developer_name: str = developer.name if developer else "حَـــــنَّـــــا"
                developer_avatar: Optional[str] = developer.avatar.url if developer and developer.avatar else None
                
                # Count current prisoners (muted users)
                prisoner_count: int = 0
                if interaction.guild:
                    for member in interaction.guild.members:
                        if self.bot.is_user_muted(member):
                            prisoner_count += 1
                
                # Get bot uptime
                uptime_seconds = (datetime.now() - self.bot.start_time).total_seconds() if hasattr(self.bot, 'start_time') else 0
                hours = int(uptime_seconds // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                uptime_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                
                # Create main embed
                embed: discord.Embed = discord.Embed(
                    color=0xFF4500  # Orange-red color
                )
                
                # Developer section
                embed.add_field(
                    name="Developer",
                    value=(
                        f"<@{self.bot.developer_id}>"
                    ),
                    inline=True
                )
                
                # Version
                embed.add_field(
                    name="Version",
                    value=(
                        f"**{Version.get_version_string()}**"
                    ),
                    inline=True
                )
                
                # Statistics
                embed.add_field(
                    name="Live Stats",
                    value=(
                        f"**Prisoners:** {prisoner_count}\n"
                        f"**Uptime:** {uptime_str}"
                    ),
                    inline=True
                )
                
                # Add spacing and description
                embed.add_field(name="\u200b", value="\u200b", inline=False)
                embed.add_field(
                    name="\u200b",
                    value="AI-powered prison bot for **discord.gg/syria**",
                    inline=False
                )
                
                # Add spacing
                embed.add_field(name="\u200b", value="\u200b", inline=False)
                
                # Technology Stack
                embed.add_field(
                    name="🔧 Technology Stack",
                    value=(
                        "• **Python 3.12**\n"
                        "• **Discord.py 2.3.2**\n"
                        "• **GPT-3.5-turbo**\n"
                        "• **OpenAI 0.28.1**\n"
                        "• **SQLite3**\n"
                        "• **PM2 Process Manager**"
                    ),
                    inline=False
                )
                
                # Add spacing
                embed.add_field(name="\u200b", value="\u200b", inline=False)
                
                # Project Statistics
                embed.add_field(
                    name="📊 Project Statistics",
                    value=(
                        "**Total Lines:** 3,057\n"
                        "**Core Files:** 15 modules\n"
                        "**Development Time:** 60 hours"
                    ),
                    inline=True
                )
                
                # Activity Info
                embed.add_field(
                    name="📅 Activity",
                    value=(
                        "**Active Since:** Sep 1, 2025\n"
                        "**Last Update:** Today\n"
                        "**Deployment:** 24/7"
                    ),
                    inline=True
                )
                
                # Empty field for layout balance
                embed.add_field(name="\u200b", value="\u200b", inline=True)
                
                # Set thumbnail to developer avatar
                if developer_avatar:
                    embed.set_thumbnail(url=developer_avatar)
                
                # Create view with buttons
                view = View()
                
                # GitHub button
                github_button = Button(
                    label="GitHub",
                    style=discord.ButtonStyle.link,
                    url="https://github.com/trippixn963/AzabBot",
                    emoji="📦"
                )
                view.add_item(github_button)
                
                # Latest Release button
                release_button = Button(
                    label=f"v{Version.get_version_string()}",
                    style=discord.ButtonStyle.link,
                    url="https://github.com/trippixn963/AzabBot/releases/latest",
                    emoji="🚀"
                )
                view.add_item(release_button)
                
                await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
                
                # Log command usage
                logger.info(f"Credits viewed by {interaction.user.name}")
                
            except Exception as e:
                logger.error(f"Credits command error: {e}")
                await interaction.response.send_message(
                    "❌ Failed to load credits. Please try again later.",
                    ephemeral=True
                )
        
        return credits