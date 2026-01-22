"""
AzabBot - Messages Handler
==========================

Handles message delete, edit, and bulk delete logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import io
from typing import TYPE_CHECKING, Optional, List, Tuple

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class MessageLogsMixin:
    """Mixin for message logging."""

    async def log_message_delete(
        self: "LoggingService",
        message: discord.Message,
        attachments: Optional[List[Tuple[str, bytes]]] = None,
    ) -> None:
        """Log a message deletion."""
        if not self._should_log(message.guild.id if message.guild else None, message.author.id):
            return

        from ..categories import LogCategory
        from ..views import MessageLogView

        embed = self._create_embed("🗑️ Message Deleted", EmbedColors.LOG_NEGATIVE, category="Message Delete", user_id=message.author.id)
        embed.add_field(name="Author", value=self._format_user_field(message.author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)

        content = f"```{message.content[:900]}```" if message.content else "*(no content)*"
        embed.add_field(name="Content", value=content, inline=False)

        if message.attachments:
            att_names = [f"📎 {att.filename}" for att in message.attachments[:5]]
            embed.add_field(name="Attachments", value="\n".join(att_names), inline=True)

        if message.reference and message.reference.message_id:
            channel_id = message.reference.channel_id or message.channel.id
            guild_id = message.guild.id if message.guild else 0
            reply_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message.reference.message_id}"
            embed.add_field(
                name="Reply To",
                value=f"[Jump to message]({reply_url})",
                inline=True,
            )

        self._set_user_thumbnail(embed, message.author)

        files = []
        if attachments:
            for filename, data in attachments[:5]:
                files.append(discord.File(io.BytesIO(data), filename=filename))

        guild_id = message.guild.id if message.guild else 0
        view = MessageLogView(message.author.id, guild_id)

        await self._send_log(LogCategory.MESSAGES, embed, files, user_id=message.author.id, view=view)

    async def log_message_edit(
        self: "LoggingService",
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        """Log a message edit."""
        if not self._should_log(after.guild.id if after.guild else None, after.author.id):
            return

        if before.content == after.content:
            return

        from ..categories import LogCategory
        from ..views import MessageLogView

        embed = self._create_embed("✏️ Message Edited", EmbedColors.WARNING, category="Message Edit", user_id=after.author.id)
        embed.add_field(name="Author", value=self._format_user_field(after.author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(after.channel), inline=True)

        before_content = f"```{before.content[:400]}```" if before.content else "*(empty)*"
        after_content = f"```{after.content[:400]}```" if after.content else "*(empty)*"

        embed.add_field(name="Before", value=before_content, inline=False)
        embed.add_field(name="After", value=after_content, inline=False)

        self._set_user_thumbnail(embed, after.author)

        guild_id = after.guild.id if after.guild else 0
        view = MessageLogView(after.author.id, guild_id, message_url=after.jump_url)

        await self._send_log(LogCategory.MESSAGES, embed, user_id=after.author.id, view=view)

    async def log_bulk_delete(
        self: "LoggingService",
        channel: discord.TextChannel,
        count: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a bulk message delete."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🗑️ Bulk Delete", EmbedColors.LOG_NEGATIVE, category="Bulk Delete")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        embed.add_field(name="Messages", value=f"**{count}**", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.MESSAGES, embed)
