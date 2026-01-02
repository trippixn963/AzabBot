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

import base64
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING, Optional, List

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.constants import SNIPE_MAX_AGE
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


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
    @app_commands.describe(
        number="Which deleted message to view (1=most recent, up to 10)",
        user="Filter by a specific user's deleted messages",
    )
    async def snipe(
        self,
        interaction: discord.Interaction,
        number: Optional[app_commands.Range[int, 1, 10]] = 1,
        user: Optional[discord.User] = None,
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

            # Get snipes from database (fetch more if filtering by user)
            fetch_limit = 50 if user else 10
            snipes = self.db.get_snipes(channel_id, limit=fetch_limit)

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

            # Apply user filter if specified
            if user:
                fresh_snipes = [s for s in fresh_snipes if s.get("author_id") == user.id]

                if not fresh_snipes:
                    logger.info("Snipe User Filter Empty", [
                        ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                        ("Mod ID", str(interaction.user.id)),
                        ("Channel", f"#{interaction.channel.name}"),
                        ("Filter User", f"{user} ({user.id})"),
                    ])
                    await interaction.response.send_message(
                        f"No recently deleted messages from {user.mention} in this channel.",
                        ephemeral=True,
                    )
                    return

            if not fresh_snipes:
                await interaction.response.send_message(
                    "No recently deleted messages in this channel.",
                    ephemeral=True,
                )
                return

            # Check if requested number exists
            index = number - 1
            if index >= len(fresh_snipes):
                filter_text = f" from {user.mention}" if user else ""
                await interaction.response.send_message(
                    f"Only {len(fresh_snipes)} deleted message(s){filter_text} cached. Use `/snipe {len(fresh_snipes)}` or lower.",
                    ephemeral=True,
                )
                return

            snipe_data = fresh_snipes[index]
            deleted_at = snipe_data.get("deleted_at", 0)

            # Get snipe data
            author_id = snipe_data.get("author_id")
            author_name = snipe_data.get("author_name", "Unknown")
            author_display = snipe_data.get("author_display", "Unknown")
            author_avatar = snipe_data.get("author_avatar")
            content = snipe_data.get("content", "")
            attachment_urls = snipe_data.get("attachment_urls", [])
            attachment_data = snipe_data.get("attachment_data", [])  # Base64 encoded files from DB
            sticker_urls = snipe_data.get("sticker_urls", [])

            # Tree logging
            content_preview = (content[:50] + "...") if len(content) > 50 else (content or "(no text)")
            log_details = [
                ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                        ("Mod ID", str(interaction.user.id)),
                ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                ("Target", f"{author_name} ({author_id})"),
                ("Message #", str(number)),
            ]
            if user:
                log_details.append(("Filter", f"{user} ({user.id})"))
            log_details.extend([
                ("Content", content_preview),
                ("Attachments", str(len(attachment_urls))),
                ("Cached Files", str(len(attachment_data))),
                ("Stickers", str(len(sticker_urls))),
            ])
            logger.tree("SNIPE USED", log_details, emoji="🎯")

            # Build plain text message
            lines = []

            # Author line - mention with display name
            lines.append(f"<@{author_id}> ({author_display})")

            # Content in quote block
            if content:
                # Split content into lines and quote each
                for line in content[:2000].split("\n"):
                    lines.append(f"> {line}")

            # Prepare files to upload from database cache
            files_to_send: List[discord.File] = []

            if attachment_data:
                # We have actual file bytes stored in DB - create discord.File objects
                for att in attachment_data[:4]:  # Limit to 4 files
                    try:
                        filename = att.get("filename", "file")
                        data_b64 = att.get("data", "")
                        if data_b64:
                            file_bytes = base64.b64decode(data_b64)
                            file_obj = discord.File(BytesIO(file_bytes), filename=filename)
                            files_to_send.append(file_obj)
                    except Exception as e:
                        logger.warning("Snipe Attachment Decode Failed", [
                            ("Filename", att.get("filename", "unknown")),
                            ("Error", str(e)[:50]),
                        ])

            # Show attachment info (URLs may be expired but show filenames)
            if attachment_urls and not files_to_send:
                att_names = [att.get("filename", "file") for att in attachment_urls[:5]]
                lines.append(f"📎 {', '.join(att_names)}")

            # Try to get actual stickers to send
            stickers_to_send: List[discord.GuildSticker] = []
            if sticker_urls and interaction.guild:
                for sticker_data in sticker_urls[:1]:  # Discord only allows 1 sticker per message
                    sticker_id = sticker_data.get("id")
                    if sticker_id:
                        try:
                            sticker = await interaction.guild.fetch_sticker(sticker_id)
                            if sticker:
                                stickers_to_send.append(sticker)
                        except (discord.NotFound, discord.HTTPException):
                            # Sticker not found or not accessible, show name instead
                            pass

                # If we couldn't get the sticker, show the name
                if not stickers_to_send:
                    sticker_names = [s.get("name", "sticker") for s in sticker_urls[:3]]
                    lines.append(f"🎨 Stickers: {', '.join(sticker_names)}")

            # Relative timestamp footer
            deleted_timestamp = int(deleted_at)
            lines.append(f"-# Deleted <t:{deleted_timestamp}:R>")

            message_content = "\n".join(lines)

            # Send public message with files and/or stickers
            if files_to_send and stickers_to_send:
                await interaction.response.send_message(content=message_content, files=files_to_send, stickers=stickers_to_send)
            elif files_to_send:
                await interaction.response.send_message(content=message_content, files=files_to_send)
            elif stickers_to_send:
                await interaction.response.send_message(content=message_content, stickers=stickers_to_send)
            else:
                await interaction.response.send_message(content=message_content)

            # Log to server logs
            await self._log_snipe_usage(
                interaction=interaction,
                target_id=author_id,
                target_name=author_name,
                message_number=number,
                content_preview=content_preview,
                filter_user=user,
            )

        except discord.HTTPException as e:
            logger.error("Snipe Command Failed (HTTP)", [
                ("Error", str(e)),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
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
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
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
    @app_commands.describe(
        number="Which edited message to view (1=most recent, up to 10)",
        user="Filter by a specific user's edited messages",
    )
    async def editsnipe(
        self,
        interaction: discord.Interaction,
        number: Optional[app_commands.Range[int, 1, 10]] = 1,
        user: Optional[discord.User] = None,
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

            # Apply user filter if specified
            if user:
                fresh_edits = [e for e in fresh_edits if e.get("author_id") == user.id]

                if not fresh_edits:
                    logger.info("Editsnipe User Filter Empty", [
                        ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                        ("Mod ID", str(interaction.user.id)),
                        ("Channel", f"#{interaction.channel.name}"),
                        ("Filter User", f"{user} ({user.id})"),
                    ])
                    await interaction.response.send_message(
                        f"No recently edited messages from {user.mention} in this channel.",
                        ephemeral=True,
                    )
                    return

            if not fresh_edits:
                await interaction.response.send_message(
                    "No recently edited messages in this channel.",
                    ephemeral=True,
                )
                return

            # Check if requested number exists
            index = number - 1
            if index >= len(fresh_edits):
                filter_text = f" from {user.mention}" if user else ""
                await interaction.response.send_message(
                    f"Only {len(fresh_edits)} edited message(s){filter_text} cached. Use `/editsnipe {len(fresh_edits)}` or lower.",
                    ephemeral=True,
                )
                return

            edit_data = fresh_edits[index]
            edited_at = edit_data.get("edited_at", 0)

            # Get edit data
            author_id = edit_data.get("author_id")
            author_name = edit_data.get("author_name", "Unknown")
            author_display = edit_data.get("author_display", "Unknown")
            author_avatar = edit_data.get("author_avatar")
            before_content = edit_data.get("before_content", "")
            after_content = edit_data.get("after_content", "")
            before_attachments = edit_data.get("before_attachments", [])
            after_attachments = edit_data.get("after_attachments", [])
            jump_url = edit_data.get("jump_url", "")

            # Find removed attachments (in before but not in after)
            after_urls = {att.get("url") for att in after_attachments}
            removed_attachments = [att for att in before_attachments if att.get("url") not in after_urls]

            # Tree logging
            before_preview = (before_content[:30] + "...") if len(before_content) > 30 else (before_content or "(empty)")
            after_preview = (after_content[:30] + "...") if len(after_content) > 30 else (after_content or "(empty)")
            log_details = [
                ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                        ("Mod ID", str(interaction.user.id)),
                ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                ("Target", f"{author_name} ({author_id})"),
                ("Message #", str(number)),
            ]
            if user:
                log_details.append(("Filter", f"{user} ({user.id})"))
            log_details.extend([
                ("Before", before_preview),
                ("After", after_preview),
                ("Removed Attachments", str(len(removed_attachments))),
            ])
            logger.tree("EDITSNIPE USED", log_details, emoji="✏️")

            # Build plain text message
            lines = []

            # Author line - mention with display name
            lines.append(f"<@{author_id}> ({author_display})")

            # Before content
            lines.append("**Before:**")
            if before_content:
                for line in before_content[:1000].split("\n"):
                    lines.append(f"> {line}")
            else:
                lines.append("> *(empty)*")

            # After content
            lines.append("**After:**")
            if after_content:
                for line in after_content[:1000].split("\n"):
                    lines.append(f"> {line}")
            else:
                lines.append("> *(empty)*")

            # Show removed attachments
            if removed_attachments:
                att_names = [att.get("filename", "file") for att in removed_attachments[:5]]
                lines.append(f"📎 Removed: {', '.join(att_names)}")

            # Relative timestamp footer
            edited_timestamp = int(edited_at)
            lines.append(f"-# Edited <t:{edited_timestamp}:R>")

            message_content = "\n".join(lines)

            # Create view with jump button if we have a URL
            view = None
            if jump_url:
                view = discord.ui.View()
                view.add_item(discord.ui.Button(
                    label="Message",
                    url=jump_url,
                    style=discord.ButtonStyle.link,
                    emoji=discord.PartialEmoji(name="message", id=1452783032460247150),
                ))

            # Send public message (not ephemeral)
            await interaction.response.send_message(content=message_content, view=view)

            # Log to server logs
            await self._log_editsnipe_usage(
                interaction=interaction,
                target_id=author_id,
                target_name=author_name,
                message_number=number,
                before_preview=before_preview,
                after_preview=after_preview,
                filter_user=user,
            )

        except discord.HTTPException as e:
            logger.error("Editsnipe Command Failed (HTTP)", [
                ("Error", str(e)),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
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
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
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
                    ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                        ("Mod ID", str(interaction.user.id)),
                    ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                    ("Target", f"{target.name} ({target.nick})" if hasattr(target, 'nick') and target.nick else target.name),
                    ("Target ID", str(target.id)),
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
                    ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                        ("Mod ID", str(interaction.user.id)),
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
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
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
        filter_user: Optional[discord.User] = None,
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
            if filter_user:
                embed.add_field(
                    name="Filter",
                    value=f"{filter_user.mention}\n`{filter_user.id}`",
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
        filter_user: Optional[discord.User] = None,
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
            if filter_user:
                embed.add_field(
                    name="Filter",
                    value=f"{filter_user.mention}\n`{filter_user.id}`",
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
