"""
Azab Discord Bot - Snipe Command Cog
=====================================

View deleted and edited messages in a channel.

Features:
    /snipe [number] - View deleted messages (1-10)
    /editsnipe [number] - View edited messages (1-10)
    /clearsnipe [@user] - Clear both snipe caches (mod only)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, has_mod_role, EmbedColors, NY_TZ
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
    """Cog for sniping deleted and edited messages."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("Snipe Cog Loaded", [
            ("Commands", "/snipe, /editsnipe, /clearsnipe"),
            ("Deleted Storage", "Database (persists)"),
            ("Edited Storage", "Memory (session)"),
            ("Max Age", f"{SNIPE_MAX_AGE}s"),
        ], emoji="🎯")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use snipe commands."""
        return has_mod_role(interaction.user)

    # =========================================================================
    # Snipe Command
    # =========================================================================

    @app_commands.command(name="snipe", description="View deleted messages in this channel")
    @app_commands.describe(number="Which deleted message to view (1=most recent, up to 10)")
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
    # Edit Snipe Command
    # =========================================================================

    @app_commands.command(name="editsnipe", description="View edited messages in this channel")
    @app_commands.describe(number="Which edited message to view (1=most recent, up to 10)")
    async def editsnipe(
        self,
        interaction: discord.Interaction,
        number: Optional[app_commands.Range[int, 1, 10]] = 1,
    ) -> None:
        """Show edited messages in the current channel."""
        if not interaction.guild or not interaction.channel:
            await interaction.response.send_message(
                "This command can only be used in a server channel.",
                ephemeral=True,
            )
            return

        try:
            channel_id = interaction.channel.id

            # Get edit snipes from in-memory cache
            edit_cache = getattr(self.bot, "_editsnipe_cache", {})
            channel_edits = list(edit_cache.get(channel_id, []))

            if not channel_edits:
                logger.debug(f"Editsnipe attempted but no cache for channel {channel_id}")
                await interaction.response.send_message(
                    "No recently edited messages in this channel.",
                    ephemeral=True,
                )
                return

            # Filter out stale messages and developer messages
            now = datetime.now(NY_TZ).timestamp()
            fresh_edits = [
                e for e in channel_edits
                if (now - e.get("edited_at", 0)) <= SNIPE_MAX_AGE
                and e.get("author_id") != self.config.developer_id
            ]

            if not fresh_edits:
                await interaction.response.send_message(
                    "No recently edited messages in this channel.",
                    ephemeral=True,
                )
                return

            # Check if requested number exists
            index = number - 1
            if index >= len(fresh_edits):
                await interaction.response.send_message(
                    f"Only {len(fresh_edits)} edited message(s) cached. Use `/editsnipe {len(fresh_edits)}` or lower.",
                    ephemeral=True,
                )
                return

            edit_data = fresh_edits[index]
            edited_at = edit_data.get("edited_at", 0)

            # Get edit data
            author_id = edit_data.get("author_id")
            author_name = edit_data.get("author_name", "Unknown")
            before_content = edit_data.get("before_content", "")
            after_content = edit_data.get("after_content", "")
            jump_url = edit_data.get("jump_url", "")

            # Tree logging
            before_preview = (before_content[:30] + "...") if len(before_content) > 30 else (before_content or "(empty)")
            after_preview = (after_content[:30] + "...") if len(after_content) > 30 else (after_content or "(empty)")
            logger.tree("EDITSNIPE USED", [
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                ("Target", f"{author_name} ({author_id})"),
                ("Message #", str(number)),
                ("Before", before_preview),
                ("After", after_preview),
            ], emoji="✏️")

            # Build plain text message (public, not embed)
            # Truncate if too long
            if len(before_content) > 800:
                before_content = before_content[:797] + "..."
            if len(after_content) > 800:
                after_content = after_content[:797] + "..."

            message_lines = [
                f"<@{author_id}> edited their message:",
                f"**Before:** {before_content or '*(empty)*'}",
                f"**After:** {after_content or '*(empty)*'}",
            ]

            # Add jump link if available
            if jump_url:
                message_lines.append(f"-# [Jump to message]({jump_url})")

            # Add edited time
            message_lines.append(f"-# Edited <t:{int(edited_at)}:R>")

            snipe_message = "\n".join(message_lines)

            # Send public message (not ephemeral)
            await interaction.response.send_message(snipe_message)

            # Log to server logs
            await self._log_editsnipe_usage(
                interaction=interaction,
                target_id=author_id,
                target_name=author_name,
                message_number=number,
                before_preview=before_preview,
                after_preview=after_preview,
            )

        except discord.HTTPException as e:
            logger.error("Editsnipe Command Failed (HTTP)", [
                ("Error", str(e)),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Channel", str(interaction.channel.id) if interaction.channel else "Unknown"),
            ])
            try:
                await interaction.followup.send(
                    "Failed to send editsnipe result. Please try again.",
                    ephemeral=True,
                )
            except Exception:
                pass

        except Exception as e:
            logger.error("Editsnipe Command Failed", [
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

    @app_commands.command(name="clearsnipe", description="Clear snipe caches for this channel")
    @app_commands.describe(
        target="Clear snipes from a specific user, or leave empty for all",
    )
    async def clearsnipe(
        self,
        interaction: discord.Interaction,
        target: Optional[discord.User] = None,
    ) -> None:
        """Clear both deleted and edited snipe caches."""
        if not interaction.guild or not interaction.channel:
            await interaction.response.send_message(
                "This command can only be used in a server channel.",
                ephemeral=True,
            )
            return

        try:
            channel_id = interaction.channel.id

            # Clear deleted snipes from database
            if target:
                cleared_deleted = self.db.clear_snipes(channel_id, user_id=target.id)
            else:
                cleared_deleted = self.db.clear_snipes(channel_id)

            # Clear edit snipes from memory
            cleared_edits = 0
            edit_cache = getattr(self.bot, "_editsnipe_cache", {})
            if channel_id in edit_cache:
                if target:
                    # Filter out edits from specific user
                    original_len = len(edit_cache[channel_id])
                    edit_cache[channel_id] = type(edit_cache[channel_id])(
                        e for e in edit_cache[channel_id]
                        if e.get("author_id") != target.id
                    )
                    cleared_edits = original_len - len(edit_cache[channel_id])
                else:
                    # Clear all edits for this channel
                    cleared_edits = len(edit_cache[channel_id])
                    edit_cache[channel_id].clear()

            total_cleared = cleared_deleted + cleared_edits

            if target:
                # Tree logging
                logger.tree("SNIPE CACHE CLEARED (User)", [
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                    ("Target", f"{target} ({target.id})"),
                    ("Deleted", f"{cleared_deleted} messages"),
                    ("Edits", f"{cleared_edits} messages"),
                ], emoji="🧹")

                await interaction.response.send_message(
                    f"Cleared **{cleared_deleted}** deleted + **{cleared_edits}** edited message(s) from {target.mention}.",
                    ephemeral=True,
                )
            else:
                # Tree logging
                logger.tree("SNIPE CACHE CLEARED (All)", [
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                    ("Deleted", f"{cleared_deleted} messages"),
                    ("Edits", f"{cleared_edits} messages"),
                ], emoji="🧹")

                await interaction.response.send_message(
                    f"Cleared **{cleared_deleted}** deleted + **{cleared_edits}** edited message(s) from this channel.",
                    ephemeral=True,
                )

            # Log to server logs
            await self._log_clearsnipe_usage(
                interaction=interaction,
                target=target,
                cleared_deleted=cleared_deleted,
                cleared_edits=cleared_edits,
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

    async def _log_editsnipe_usage(
        self,
        interaction: discord.Interaction,
        target_id: int,
        target_name: str,
        message_number: int,
        before_preview: str,
        after_preview: str,
    ) -> None:
        """Log editsnipe usage to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="✏️ Editsnipe Used",
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
                name="Before",
                value=f"```{before_preview[:100]}```" if before_preview else "*(empty)*",
                inline=False,
            )
            embed.add_field(
                name="After",
                value=f"```{after_preview[:100]}```" if after_preview else "*(empty)*",
                inline=False,
            )

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed,
            )

        except Exception as e:
            logger.debug(f"Failed to log editsnipe usage: {e}")

    async def _log_clearsnipe_usage(
        self,
        interaction: discord.Interaction,
        target: Optional[discord.User],
        cleared_deleted: int,
        cleared_edits: int,
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
                name="Deleted",
                value=f"`{cleared_deleted}` message(s)",
                inline=True,
            )
            embed.add_field(
                name="Edits",
                value=f"`{cleared_edits}` message(s)",
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
