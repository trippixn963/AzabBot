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
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from src.core.logger import logger


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
                    title="🔥 AZAB BOT - CREDITS & INFORMATION",
                    description=(
                        "**Advanced Discord Prison Bot**\n"
                        "Sophisticated AI-powered bot for ragebaiting muted users\n"
                        "Built exclusively for **discord.gg/syria**\n"
                    ),
                    color=0xFF4500,  # Orange-red color
                    timestamp=datetime.now(timezone.utc)
                )
                
                # Developer section
                embed.add_field(
                    name="👨‍💻 Developer",
                    value=(
                        f"**{developer_name}** (حَـــــنَّـــــا)\n"
                        f"Solo developed over 40-60 hours\n"
                        f"Custom built for Syria Discord"
                    ),
                    inline=False
                )
                
                # Technical specifications
                embed.add_field(
                    name="🔧 Tech Stack",
                    value=(
                        "**Language:** Python 3.12\n"
                        "**Framework:** Discord.py 2.3.2\n"
                        "**AI Model:** GPT-3.5-turbo\n"
                        "**Database:** SQLite\n"
                        "**Hosting:** VPS with PM2"
                    ),
                    inline=True
                )
                
                # Statistics
                embed.add_field(
                    name="📊 Statistics",
                    value=(
                        f"**Current Prisoners:** {prisoner_count}\n"
                        f"**Uptime:** {uptime_str}\n"
                        f"**Total Servers:** {len(self.bot.guilds)}\n"
                        f"**Code Lines:** ~850\n"
                        f"**Version:** v2.2.0"
                    ),
                    inline=True
                )
                
                # Add spacing
                embed.add_field(name="\u200b", value="\u200b", inline=False)
                
                # Features list
                embed.add_field(
                    name="✨ Key Features",
                    value=(
                        "• **AI Ragebaiting** - GPT-3.5 powered responses\n"
                        "• **Prisoner Database** - Tracks all mute history\n"
                        "• **Smart Rate Limiting** - 10s cooldown with buffering\n"
                        "• **Auto Log Cleanup** - 30-day retention\n"
                        "• **Professional Embeds** - Welcome/release messages\n"
                        "• **Developer Recognition** - Special creator responses"
                    ),
                    inline=False
                )
                
                # Architecture
                embed.add_field(
                    name="🏗️ Architecture",
                    value=(
                        "• **Modular Design** - Organized handlers/services\n"
                        "• **Persistent State** - Survives restarts\n"
                        "• **Dynamic Presence** - Live prisoner count\n"
                        "• **Mute Detection** - Role & embed monitoring\n"
                        "• **24/7 Operation** - PM2 process management"
                    ),
                    inline=False
                )
                
                # Links section
                embed.add_field(
                    name="🔗 Links",
                    value=(
                        "**GitHub:** [AzabBot Repository](https://github.com/trippixn963/AzabBot)\n"
                        "**Server:** [discord.gg/syria](https://discord.gg/syria)\n"
                        "**Latest Release:** [v2.2.0](https://github.com/trippixn963/AzabBot/releases/latest)"
                    ),
                    inline=False
                )
                
                # Set thumbnail to bot avatar
                if self.bot.user.avatar:
                    embed.set_thumbnail(url=self.bot.user.avatar.url)
                
                # Set footer with developer info and avatar
                embed.set_footer(
                    text=f"Developed with ❤️ by {developer_name}",
                    icon_url=developer_avatar
                )
                
                # Set author field
                embed.set_author(
                    name="Azab Bot",
                    icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None,
                    url="https://github.com/trippixn963/AzabBot"
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=False)
                
                # Log command usage
                logger.info(f"Credits viewed by {interaction.user.name}")
                
            except Exception as e:
                logger.error(f"Credits command error: {e}")
                await interaction.response.send_message(
                    "❌ Failed to load credits. Please try again later.",
                    ephemeral=True
                )
        
        return credits