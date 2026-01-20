"""
Azab Discord Bot - Editsnipe Command Mixin
==========================================

/editsnipe command implementation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

from src.core.logger import logger
from src.core.config import NY_TZ
from src.core.constants import SNIPE_MAX_AGE, EMOJI_ID_MESSAGE

if TYPE_CHECKING:
    from .cog import SnipeCog


class EditsnipeCmdMixin:
    """Mixin for /editsnipe command."""

    @app_commands.command(name="editsnipe", description="View edited messages in this channel")
    @app_commands.describe(
        number="Which edited message to view (1=most recent, up to 10)",
        user="Filter by a specific user's edited messages",
    )
    async def editsnipe(
        self: "SnipeCog",
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
                    emoji=discord.PartialEmoji(name="message", id=EMOJI_ID_MESSAGE),
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


__all__ = ["EditsnipeCmdMixin"]
