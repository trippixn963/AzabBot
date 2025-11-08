"""
Azab Discord Bot - Purge Prison Command
========================================

Slash command implementation for purging all messages from the prison channel.
This is a one-time cleanup command that removes all messages (up to 10,000).

Features:
- Delete all messages in prison channel
- Uses bulk delete for recent messages
- Individual deletion for old messages
- Administrator-only access
- Progress updates during deletion

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.4.0
"""

import discord
from discord import app_commands
import asyncio
import os
from typing import Any, Optional
from datetime import datetime, timezone, timedelta

from src.core.logger import logger


class PurgePrisonCommand:
    """
    Discord slash command for purging all messages from prison channel.

    This command removes all messages from the prison channel to clean it up.
    Uses efficient bulk deletion for recent messages and individual deletion
    for older messages. Only administrators can execute this command.
    """

    def __init__(self, bot: Any) -> None:
        """
        Initialize the purge prison command.

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
        @app_commands.command(name="purge_prison", description="Purge all messages from prison channel")
        @app_commands.default_permissions(administrator=True)
        async def purge_prison(interaction: discord.Interaction) -> None:
            """
            Handle the /purge_prison slash command.

            Deletes all messages from the prison channel (up to 10,000 messages).
            Uses bulk deletion for recent messages and individual deletion for old ones.

            Args:
                interaction (discord.Interaction): The Discord interaction object
            """
            await interaction.response.defer(ephemeral=True)

            prison_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.prison_channel_id)

            if not prison_channel:
                await interaction.followup.send("❌ Prison channel not found!", ephemeral=True)
                return

            logger.info(f"Starting prison channel purge by {interaction.user.name}")

            try:
                deleted_count: int = 0
                total_scanned: int = 0
                two_weeks_ago: datetime = datetime.now(timezone.utc) - timedelta(days=14)

                await interaction.followup.send(
                    "🧹 **Starting prison channel purge...**\nThis may take several minutes. I'll keep you updated.",
                    ephemeral=True
                )

                recent_messages = []
                last_update_time = datetime.now()
                update_interval = timedelta(seconds=30)

                logger.info(f"Scanning prison channel history (limit: {os.getenv('PURGE_SCAN_LIMIT', '100000')})")

                async for message in prison_channel.history(limit=int(os.getenv('PURGE_SCAN_LIMIT', '100000'))):
                    total_scanned += 1

                    if message.created_at > two_weeks_ago:
                        recent_messages.append(message)
                    else:
                        # Delete old messages immediately one by one (faster)
                        try:
                            await message.delete()
                            deleted_count += 1
                            await asyncio.sleep(0.3)  # Reduced from 0.5s
                        except Exception:
                            pass

                    # Progress update every 1000 messages
                    if total_scanned % 1000 == 0:
                        logger.info(f"Scanned {total_scanned} messages, deleted {deleted_count} so far...")

                    # Send progress updates every 30 seconds
                    if datetime.now() - last_update_time > update_interval:
                        try:
                            await interaction.followup.send(
                                f"📊 **Progress Update:**\n"
                                f"• Scanned: {total_scanned} messages\n"
                                f"• Deleted: {deleted_count} messages\n"
                                f"• Still processing...",
                                ephemeral=True
                            )
                            last_update_time = datetime.now()
                        except Exception:
                            pass

                    # Process recent messages in batches of 100
                    if len(recent_messages) >= 100:
                        try:
                            await prison_channel.delete_messages(recent_messages)
                            deleted_count += len(recent_messages)
                            logger.info(f"Bulk deleted {len(recent_messages)} messages (Total: {deleted_count})")
                            recent_messages = []
                            await asyncio.sleep(1)
                        except discord.HTTPException as e:
                            logger.warning(f"Bulk delete failed: {str(e)[:100]}")
                            for msg in recent_messages:
                                try:
                                    await msg.delete()
                                    deleted_count += 1
                                    await asyncio.sleep(0.3)
                                except Exception:
                                    pass
                            recent_messages = []

                # Process remaining recent messages
                if recent_messages:
                    try:
                        await prison_channel.delete_messages(recent_messages)
                        deleted_count += len(recent_messages)
                        logger.info(f"Bulk deleted final {len(recent_messages)} messages")
                    except discord.HTTPException:
                        for msg in recent_messages:
                            try:
                                await msg.delete()
                                deleted_count += 1
                                await asyncio.sleep(0.3)
                            except Exception:
                                pass

                embed = discord.Embed(
                    title="🧹 Prison Channel Purged",
                    description=f"Successfully cleaned the prison channel!",
                    color=int(os.getenv('EMBED_COLOR_SUCCESS', '0x00FF00'), 16)
                )

                embed.add_field(name="📊 Messages Scanned", value=str(total_scanned), inline=True)
                embed.add_field(name="🗑️ Messages Deleted", value=str(deleted_count), inline=True)
                embed.add_field(name="✨ Channel Status", value="Clean", inline=True)

                embed.add_field(name="👤 Executed By", value=interaction.user.mention, inline=True)
                embed.add_field(name="📍 Channel", value=prison_channel.mention, inline=True)
                embed.add_field(name="⏱️ Completed", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)

                embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
                developer: Optional[discord.User] = await self.bot.fetch_user(interaction.user.id)
                developer_avatar: Optional[str] = developer.avatar.url if developer and developer.avatar else None
                embed.set_footer(text=f"Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}", icon_url=developer_avatar)

                await interaction.followup.send(embed=embed, ephemeral=True)

                logger.tree("PRISON CHANNEL PURGED", [
                    ("By", str(interaction.user)),
                    ("Scanned", str(total_scanned)),
                    ("Deleted", str(deleted_count)),
                    ("Channel", prison_channel.name)
                ], "🧹")

            except Exception as e:
                logger.error(f"Purge Prison Error: {str(e)[:100]}")
                await interaction.followup.send(
                    f"❌ **Error during purge:**\n```{str(e)[:200]}```\nDeleted {deleted_count} messages before error.",
                    ephemeral=True
                )

        return purge_prison
