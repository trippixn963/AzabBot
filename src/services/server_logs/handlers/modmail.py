"""
Server Logs - Modmail Handler
=============================

Handles modmail logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class ModmailLogsMixin:
    """Mixin for modmail logging."""

    async def log_modmail_created(
        self: "LoggingService",
        user: discord.User,
        thread_id: int,
    ) -> None:
        """Log a modmail thread creation."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import UserIdButton, MESSAGE_EMOJI

        embed = self._create_embed(
            "📬 Modmail Created",
            EmbedColors.SUCCESS,
            category="Modmail",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Status", value="Banned User", inline=True)
        self._set_user_thumbnail(embed, user)

        view = discord.ui.View(timeout=None)
        guild_id = self.config.logging_guild_id or self.config.mod_guild_id or 0
        if guild_id and thread_id:
            thread_url = f"https://discord.com/channels/{guild_id}/{thread_id}"
            view.add_item(discord.ui.Button(
                label="Thread",
                url=thread_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.MODMAIL, embed, view=view, user_id=user.id)

    async def log_modmail_closed(
        self: "LoggingService",
        user: discord.User,
        closed_by: discord.Member,
        thread_id: int,
    ) -> None:
        """Log a modmail thread close."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import UserIdButton, MESSAGE_EMOJI

        embed = self._create_embed(
            "🔒 Modmail Closed",
            EmbedColors.LOG_NEGATIVE,
            category="Modmail",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Closed By", value=self._format_user_field(closed_by), inline=True)
        self._set_user_thumbnail(embed, closed_by)

        view = discord.ui.View(timeout=None)
        guild_id = self.config.logging_guild_id or self.config.mod_guild_id or 0
        if guild_id and thread_id:
            thread_url = f"https://discord.com/channels/{guild_id}/{thread_id}"
            view.add_item(discord.ui.Button(
                label="Thread",
                url=thread_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.MODMAIL, embed, view=view, user_id=user.id)

    async def log_modmail_message(
        self: "LoggingService",
        user: discord.User,
        direction: str,
        content: str,
        staff: Optional[discord.Member] = None,
    ) -> None:
        """Log a modmail message relay."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import UserIdButton

        if direction == "incoming":
            title = "📥 Modmail Received"
            color = EmbedColors.BLUE
        else:
            title = "📤 Modmail Sent"
            color = EmbedColors.SUCCESS

        embed = self._create_embed(
            title,
            color,
            category="Modmail",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if staff:
            embed.add_field(name="Staff", value=self._format_user_field(staff), inline=True)
        embed.add_field(name="Content", value=content[:500] if content else "*No content*", inline=False)
        self._set_user_thumbnail(embed, user)

        view = discord.ui.View(timeout=None)
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.MODMAIL, embed, view=view, user_id=user.id)


__all__ = ["ModmailLogsMixin"]
