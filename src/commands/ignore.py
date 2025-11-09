"""
Azab Discord Bot - Ignore User Command
======================================

Slash command implementation for ignoring/unignoring specific users.
Allows administrators to prevent the bot from responding to certain users.

Features:
- Ignore specific users (bot won't respond to them)
- Unignore previously ignored users
- Persistent storage of ignored users
- Administrator-only access
- Visual confirmation embeds

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
import os
from typing import Any, Optional, Literal
from datetime import datetime

from src.core.logger import logger


class IgnoreCommand:
    """
    Discord slash command for ignoring/unignoring specific users.

    This command allows administrators to add or remove users from the bot's
    ignore list. Ignored users will be completely ignored by the bot - no
    responses, no logging, no interactions.
    """

    def __init__(self, bot: Any) -> None:
        """
        Initialize the ignore command.

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
        @app_commands.command(name="ignore", description="Ignore or unignore a specific user")
        @app_commands.describe(
            action="Choose to ignore or unignore the user",
            user="The user to ignore or unignore"
        )
        async def ignore(
            interaction: discord.Interaction,
            action: Literal["ignore", "unignore"],
            user: discord.User
        ) -> None:
            """
            Handle the /ignore slash command.

            Allows administrators to ignore or unignore specific users.
            Ignored users are stored persistently and the bot won't respond to them.

            Args:
                interaction (discord.Interaction): The Discord interaction object
                action (Literal["ignore", "unignore"]): Action to perform
                user (discord.User): The user to ignore/unignore
            """
            await interaction.response.defer(ephemeral=True)

            # DESIGN: Prevent ignoring bot itself, developer, and family members
            # This is a safety mechanism to prevent accidental lockout from bot control
            # If we allowed ignoring developer, we'd lose all control over the bot
            if user.id == self.bot.user.id:
                await interaction.followup.send("❌ I cannot ignore myself!", ephemeral=True)
                return

            if user.id == self.bot.developer_id:
                await interaction.followup.send("❌ I cannot ignore my developer!", ephemeral=True)
                return

            # DESIGN: Family members can't be ignored for debugging/testing purposes
            # They need to bypass all restrictions to test bot functionality
            if user.id == self.bot.uncle_id or user.id == self.bot.brother_id:
                await interaction.followup.send("❌ I cannot ignore family members!", ephemeral=True)
                return

            if action == "ignore":
                if user.id in self.bot.ignored_users:
                    await interaction.followup.send(
                        f"ℹ️ **{user.name}** is already being ignored.",
                        ephemeral=True
                    )
                    return

                self.bot.ignored_users.add(user.id)
                self.bot._save_ignored_users()

                embed = discord.Embed(
                    title="🔇 User Ignored",
                    description=f"The bot will now ignore all messages from this user.",
                    color=int(os.getenv('EMBED_COLOR_ERROR', '0xFF0000'), 16)
                )

                embed.add_field(name="👤 User", value=user.mention, inline=True)
                embed.add_field(name="🆔 User ID", value=str(user.id), inline=True)
                embed.add_field(name="⚙️ Action", value="Ignored", inline=True)

                embed.add_field(name="📝 Effect", value="Bot will not respond to their messages", inline=False)

                embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)

                developer: Optional[discord.User] = await self.bot.fetch_user(self.bot.developer_id)
                developer_avatar: Optional[str] = developer.avatar.url if developer and developer.avatar else None
                embed.set_footer(
                    text=f"Executed by {interaction.user.name} • Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}",
                    icon_url=developer_avatar
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

                logger.tree("USER IGNORED", [
                    ("User", str(user)),
                    ("User ID", str(user.id)),
                    ("By", str(interaction.user)),
                    ("Total Ignored", str(len(self.bot.ignored_users)))
                ], "🔇")

            elif action == "unignore":
                if user.id not in self.bot.ignored_users:
                    await interaction.followup.send(
                        f"ℹ️ **{user.name}** is not currently being ignored.",
                        ephemeral=True
                    )
                    return

                self.bot.ignored_users.remove(user.id)
                self.bot._save_ignored_users()

                embed = discord.Embed(
                    title="🔊 User Unignored",
                    description=f"The bot will now respond to this user again.",
                    color=int(os.getenv('EMBED_COLOR_SUCCESS', '0x00FF00'), 16)
                )

                embed.add_field(name="👤 User", value=user.mention, inline=True)
                embed.add_field(name="🆔 User ID", value=str(user.id), inline=True)
                embed.add_field(name="⚙️ Action", value="Unignored", inline=True)

                embed.add_field(name="📝 Effect", value="Bot will respond normally to their messages", inline=False)

                embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)

                developer: Optional[discord.User] = await self.bot.fetch_user(self.bot.developer_id)
                developer_avatar: Optional[str] = developer.avatar.url if developer and developer.avatar else None
                embed.set_footer(
                    text=f"Executed by {interaction.user.name} • Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}",
                    icon_url=developer_avatar
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

                logger.tree("USER UNIGNORED", [
                    ("User", str(user)),
                    ("User ID", str(user.id)),
                    ("By", str(interaction.user)),
                    ("Total Ignored", str(len(self.bot.ignored_users)))
                ], "🔊")

        return ignore
