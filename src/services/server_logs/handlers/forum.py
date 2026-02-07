"""
AzabBot - Forum Handler
=======================

Handles forum post and tag logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors
from ..categories import LogCategory

if TYPE_CHECKING:
    from ..service import LoggingService


class ForumLogsMixin:
    """Mixin for forum post and tag logging."""

    async def log_forum_post_create(
        self: "LoggingService",
        thread: discord.Thread,
        creator: Optional[discord.Member] = None,
        content: Optional[str] = None,
    ) -> None:
        """Log a forum post creation."""
        if not self.enabled:
            return

        user_id = creator.id if creator else None
        embed = self._create_embed("📝 Forum Post Created", EmbedColors.SUCCESS, category="Forum Post", user_id=user_id)
        embed.add_field(name="Post", value=f"<#{thread.id}>", inline=True)
        if thread.parent:
            embed.add_field(name="Forum", value=self._format_channel(thread.parent), inline=True)
        if creator:
            embed.add_field(name="By", value=self._format_user_field(creator), inline=True)

        if thread.applied_tags:
            tags = ", ".join([f"`{tag.name}`" for tag in thread.applied_tags])
            embed.add_field(name="Tags", value=tags, inline=True)

        if content:
            truncated = content[:300] if len(content) > 300 else content
            embed.add_field(name="Content Preview", value=f"```{truncated}```", inline=False)

        if creator:
            self._set_user_thumbnail(embed, creator)

        await self._send_log(LogCategory.THREADS, embed, user_id=user_id)

    async def log_forum_tag_create(
        self: "LoggingService",
        forum: discord.ForumChannel,
        tag_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a forum tag creation."""
        if not self.enabled:
            return

        embed = self._create_embed("🏷️ Forum Tag Created", EmbedColors.SUCCESS, category="Forum Tag Create")
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)
        embed.add_field(name="Forum", value=self._format_channel(forum), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNEL_CHANGES, embed)

    async def log_forum_tag_delete(
        self: "LoggingService",
        forum: discord.ForumChannel,
        tag_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a forum tag deletion."""
        if not self.enabled:
            return

        embed = self._create_embed("🏷️ Forum Tag Deleted", EmbedColors.LOG_NEGATIVE, category="Forum Tag Delete")
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)
        embed.add_field(name="Forum", value=self._format_channel(forum), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNEL_CHANGES, embed)

    async def log_forum_tag_update(
        self: "LoggingService",
        forum: discord.ForumChannel,
        old_name: str,
        new_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a forum tag update."""
        if not self.enabled:
            return

        embed = self._create_embed("🏷️ Forum Tag Updated", EmbedColors.WARNING, category="Forum Tag Update")
        embed.add_field(name="Old Name", value=f"`{old_name}`", inline=True)
        embed.add_field(name="New Name", value=f"`{new_name}`", inline=True)
        embed.add_field(name="Forum", value=self._format_channel(forum), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNEL_CHANGES, embed)


__all__ = ["ForumLogsMixin"]
