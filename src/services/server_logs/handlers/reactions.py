"""
AzabBot - Reactions Handler
===========================

Handles reaction logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors
from ..categories import LogCategory
from ..views import ReactionLogView, MESSAGE_EMOJI

if TYPE_CHECKING:
    from ..service import LoggingService


class ReactionsLogsMixin:
    """Mixin for reaction logging."""

    async def log_reaction_add(
        self: "LoggingService",
        reaction: discord.Reaction,
        user: discord.Member,
        message: discord.Message,
    ) -> None:
        """Log a reaction being added."""
        if not self.enabled:
            return

        embed = self._create_embed("➕ Reaction Added", EmbedColors.SUCCESS, category="Reaction Add", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Reacted", value=f"{reaction.emoji} in {self._format_channel(message.channel)}", inline=True)

        if message.content:
            preview = message.content[:100] + "..." if len(message.content) > 100 else message.content
            embed.add_field(name="Message", value=f"```{preview}```", inline=False)

        self._set_user_thumbnail(embed, user)

        view = ReactionLogView(user.id, user.guild.id, message.jump_url)
        await self._send_log(LogCategory.REACTIONS, embed, view=view)

    async def log_reaction_remove(
        self: "LoggingService",
        reaction: discord.Reaction,
        user: discord.Member,
        message: discord.Message,
    ) -> None:
        """Log a reaction being removed."""
        if not self.enabled:
            return

        embed = self._create_embed("➖ Reaction Removed", EmbedColors.LOG_NEGATIVE, category="Reaction Remove", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Removed", value=f"{reaction.emoji} from {self._format_channel(message.channel)}", inline=True)
        self._set_user_thumbnail(embed, user)

        view = ReactionLogView(user.id, user.guild.id, message.jump_url)
        await self._send_log(LogCategory.REACTIONS, embed, view=view)

    async def log_reaction_clear(
        self: "LoggingService",
        message: discord.Message,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log all reactions being cleared from a message."""
        if not self.enabled:
            return

        embed = self._create_embed("🗑️ Reactions Cleared", EmbedColors.LOG_NEGATIVE, category="Reaction Clear")
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(
            label="Message",
            url=message.jump_url,
            style=discord.ButtonStyle.link,
            emoji=MESSAGE_EMOJI,
        ))

        await self._send_log(LogCategory.REACTIONS, embed, view=view)


__all__ = ["ReactionsLogsMixin"]
