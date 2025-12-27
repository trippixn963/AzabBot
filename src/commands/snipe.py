"""
Azab Discord Bot - Snipe Command Cog
=====================================

View deleted messages in a channel.

Features:
    /snipe [number] - View deleted messages (1-10)
    /clearsnipe [@user] - Clear snipe cache (mod only)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# How old a sniped message can be before it's considered stale (seconds)
SNIPE_MAX_AGE = 600  # 10 minutes


# =============================================================================
# Snipe Cog
# =============================================================================

class SnipeCog(commands.Cog):
    """Cog for sniping deleted messages."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("Snipe Cog Loaded", [
            ("Commands", "/snipe, /clearsnipe"),
            ("Storage", "Database (persists)"),
            ("Max Age", f"{SNIPE_MAX_AGE}s"),
        ], emoji="🎯")

    # =========================================================================
    # Snipe Command
    # =========================================================================

    @app_commands.command(name="snipe", description="View deleted messages in this channel")
    @app_commands.describe(number="Which deleted message to view (1=most recent, up to 10)")
    @app_commands.default_permissions(moderate_members=True)
    async def snipe(
        self,
        interaction: discord.Interaction,
        number: Optional[app_commands.Range[int, 1, 10]] = 1,
    ) -> None:
        """Show deleted messages in the current channel."""
        if not interaction.guild or not interaction.channel:
            await interaction.response.send_message(
                "This command can only be used in a server channel.",
                ephemeral=True,
            )
            return

        try:
            channel_id = interaction.channel.id

            # Get snipes from database
            snipes = self.db.get_snipes(channel_id, limit=10)

            if not snipes:
                logger.debug(f"Snipe attempted but no cache for channel {channel_id}")
                await interaction.response.send_message(
                    "No recently deleted messages in this channel.",
                    ephemeral=True,
                )
                return

            # Filter out stale messages and developer messages
            now = datetime.now(NY_TZ).timestamp()
            fresh_snipes = [
                s for s in snipes
                if (now - s["deleted_at"]) <= SNIPE_MAX_AGE
                and s.get("author_id") != self.config.developer_id
            ]

            if not fresh_snipes:
                await interaction.response.send_message(
                    "No recently deleted messages in this channel.",
                    ephemeral=True,
                )
                return

            # Check if requested number exists
            index = number - 1
            if index >= len(fresh_snipes):
                await interaction.response.send_message(
                    f"Only {len(fresh_snipes)} deleted message(s) cached. Use `/snipe {len(fresh_snipes)}` or lower.",
                    ephemeral=True,
                )
                return

            snipe_data = fresh_snipes[index]
            deleted_at = snipe_data.get("deleted_at", 0)

            # Get snipe data
            author_id = snipe_data.get("author_id")
            author_name = snipe_data.get("author_name", "Unknown")
            author_display = snipe_data.get("author_display", "Unknown")
            content = snipe_data.get("content", "")
            attachment_names = snipe_data.get("attachment_names", [])

            # Tree logging
            content_preview = (content[:50] + "...") if len(content) > 50 else (content or "(no text)")
            logger.tree("SNIPE USED", [
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                ("Target", f"{author_name} ({author_id})"),
                ("Message #", str(number)),
                ("Content", content_preview),
                ("Attachments", str(len(attachment_names))),
            ], emoji="🎯")

            # Build plain text message (public, not embed)
            # Format: @mention: content
            #         -# metadata underneath
            if content:
                # Truncate if too long
                if len(content) > 1500:
                    content = content[:1497] + "..."
                main_line = f"<@{author_id}>: {content}"
            else:
                main_line = f"<@{author_id}>: *(No text content)*"

            message_lines = [main_line]

            # Add attachment names if any
            if attachment_names:
                attachment_list = ", ".join(attachment_names[:4])
                message_lines.append(f"-# Attachments: {attachment_list}")

            # Add deleted time in -# small text format
            message_lines.append(f"-# Deleted <t:{int(deleted_at)}:R>")

            snipe_message = "\n".join(message_lines)

            # Send public message (not ephemeral)
            await interaction.response.send_message(snipe_message)

            # Log to server logs
            await self._log_snipe_usage(
                interaction=interaction,
                target_id=author_id,
                target_name=author_name,
                message_number=number,
                content_preview=content_preview,
            )

        except discord.HTTPException as e:
            logger.error("Snipe Command Failed (HTTP)", [
                ("Error", str(e)),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Channel", str(interaction.channel.id) if interaction.channel else "Unknown"),
            ])
            try:
                await interaction.followup.send(
                    "Failed to send snipe result. Please try again.",
                    ephemeral=True,
                )
            except Exception:
                pass

        except Exception as e:
            logger.error("Snipe Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
                ("User", f"{interaction.user} ({interaction.user.id})"),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred while sniping. Please try again.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "An error occurred while sniping. Please try again.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    # =========================================================================
    # Clear Snipe Command
    # =========================================================================

    @app_commands.command(name="clearsnipe", description="Clear snipe cache for this channel")
    @app_commands.describe(
        target="Clear snipes from a specific user, or leave empty for all",
    )
    @app_commands.default_permissions(moderate_members=True)
    async def clearsnipe(
        self,
        interaction: discord.Interaction,
        target: Optional[discord.User] = None,
    ) -> None:
        """Clear snipe cache."""
        if not interaction.guild or not interaction.channel:
            await interaction.response.send_message(
                "This command can only be used in a server channel.",
                ephemeral=True,
            )
            return

        try:
            channel_id = interaction.channel.id

            if target:
                # Clear only messages from specific user
                cleared_snipes = self.db.clear_snipes(channel_id, user_id=target.id)

                # Tree logging
                logger.tree("SNIPE CACHE CLEARED (User)", [
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                    ("Target", f"{target} ({target.id})"),
                    ("Cleared", f"{cleared_snipes} messages"),
                ], emoji="🧹")

                await interaction.response.send_message(
                    f"Cleared **{cleared_snipes}** deleted message(s) from {target.mention} in this channel.",
                    ephemeral=True,
                )

                # Log to server logs
                await self._log_clearsnipe_usage(
                    interaction=interaction,
                    target=target,
                    cleared_count=cleared_snipes,
                )

            else:
                # Clear all messages in this channel
                cleared_snipes = self.db.clear_snipes(channel_id)

                # Tree logging
                logger.tree("SNIPE CACHE CLEARED (All)", [
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                    ("Cleared", f"{cleared_snipes} messages"),
                ], emoji="🧹")

                await interaction.response.send_message(
                    f"Cleared **{cleared_snipes}** deleted message(s) from this channel's snipe cache.",
                    ephemeral=True,
                )

                # Log to server logs
                await self._log_clearsnipe_usage(
                    interaction=interaction,
                    target=None,
                    cleared_count=cleared_snipes,
                )

        except Exception as e:
            logger.error("Clear Snipe Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
                ("User", f"{interaction.user} ({interaction.user.id})"),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred while clearing snipe cache.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    # =========================================================================
    # Server Logs Integration
    # =========================================================================

    async def _log_snipe_usage(
        self,
        interaction: discord.Interaction,
        target_id: int,
        target_name: str,
        message_number: int,
        content_preview: str,
    ) -> None:
        """Log snipe usage to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🎯 Snipe Used",
                color=EmbedColors.GOLD,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Moderator",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True,
            )
            embed.add_field(
                name="Target",
                value=f"{target_name}\n`{target_id}`",
                inline=True,
            )
            embed.add_field(
                name="Channel",
                value=f"{interaction.channel.mention}" if interaction.channel else "Unknown",
                inline=True,
            )
            embed.add_field(
                name="Message #",
                value=f"`{message_number}`",
                inline=True,
            )
            embed.add_field(
                name="Content Preview",
                value=f"```{content_preview[:100]}```" if content_preview else "*(empty)*",
                inline=False,
            )

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed,
            )

        except Exception as e:
            logger.debug(f"Failed to log snipe usage: {e}")

    async def _log_clearsnipe_usage(
        self,
        interaction: discord.Interaction,
        target: Optional[discord.User],
        cleared_count: int,
    ) -> None:
        """Log clearsnipe usage to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🧹 Snipe Cache Cleared",
                color=EmbedColors.WARNING,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Moderator",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True,
            )

            if target:
                embed.add_field(
                    name="Target User",
                    value=f"{target.mention}\n`{target.id}`",
                    inline=True,
                )
            else:
                embed.add_field(
                    name="Target",
                    value="All messages",
                    inline=True,
                )

            embed.add_field(
                name="Channel",
                value=f"{interaction.channel.mention}" if interaction.channel else "Unknown",
                inline=True,
            )
            embed.add_field(
                name="Cleared",
                value=f"`{cleared_count}` message(s)",
                inline=True,
            )

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed,
            )

        except Exception as e:
            logger.debug(f"Failed to log clearsnipe usage: {e}")


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Snipe cog."""
    await bot.add_cog(SnipeCog(bot))
