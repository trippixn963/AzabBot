"""
AzabBot - Snipe Command Mixin
=============================

/snipe command implementation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import base64
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING, Optional, List

import discord
from discord import app_commands

from src.core.logger import logger
from src.core.config import NY_TZ
from src.core.constants import SNIPE_MAX_AGE, QUERY_LIMIT_SMALL, QUERY_LIMIT_MEDIUM
from src.utils.interaction import safe_respond
from src.utils.discord_rate_limit import log_http_error

if TYPE_CHECKING:
    from .cog import SnipeCog


class SnipeCmdMixin:
    """Mixin for /snipe command."""

    @app_commands.command(name="snipe", description="View deleted messages in this channel")
    @app_commands.describe(
        number="Which deleted message to view (1=most recent, up to 10)",
        user="Filter by a specific user's deleted messages",
    )
    async def snipe(
        self: "SnipeCog",
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
            fetch_limit = QUERY_LIMIT_MEDIUM if user else QUERY_LIMIT_SMALL
            snipes = self.db.get_snipes(channel_id, limit=fetch_limit)

            if not snipes:
                logger.debug("Snipe No Cache", [("Channel", str(channel_id))])
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
                and s.get("author_id") != self.config.owner_id
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

            # SECURITY: Disable all mentions to prevent @everyone/@here injection
            # Users without mention perms could have their deleted messages sniped,
            # and the bot (with admin) would then actually ping everyone
            no_mentions = discord.AllowedMentions.none()

            # Send public message with files and/or stickers
            if files_to_send and stickers_to_send:
                await interaction.response.send_message(content=message_content, files=files_to_send, stickers=stickers_to_send, allowed_mentions=no_mentions)
            elif files_to_send:
                await interaction.response.send_message(content=message_content, files=files_to_send, allowed_mentions=no_mentions)
            elif stickers_to_send:
                await interaction.response.send_message(content=message_content, stickers=stickers_to_send, allowed_mentions=no_mentions)
            else:
                await interaction.response.send_message(content=message_content, allowed_mentions=no_mentions)

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
            log_http_error(e, "Snipe Command", [
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
                ("Channel", str(interaction.channel.id) if interaction.channel else "Unknown"),
            ])
            try:
                await interaction.followup.send(
                    "Failed to send snipe result. Please try again.",
                    ephemeral=True,
                )
            except Exception as followup_error:
                logger.debug("Snipe Error Followup Failed", [
                    ("Original Error", str(e)[:50]),
                    ("Followup Error", str(followup_error)[:50]),
                ])

        except Exception as e:
            logger.error("Snipe Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
            ])
            await safe_respond(
                interaction,
                "An error occurred while sniping. Please try again.",
                ephemeral=True,
            )


__all__ = ["SnipeCmdMixin"]
