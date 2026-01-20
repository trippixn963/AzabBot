"""
Server Logs - Warnings Handler
==============================

Handles warning logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.config import EmbedColors
from src.core.database import get_db
from src.core.logger import logger

if TYPE_CHECKING:
    from ..service import LoggingService


class WarningsLogsMixin:
    """Mixin for warning logging."""

    async def log_warning_issued(
        self: "LoggingService",
        user: discord.User,
        moderator: discord.Member,
        reason: str,
        warning_count: int,
        guild_id: int,
    ) -> None:
        """Log a warning issued to a user."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import UserIdButton, CASE_EMOJI

        logger.tree("Server Logs: log_warning_issued Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Warning Count", str(warning_count)),
        ], emoji="📋")

        embed = self._create_embed(
            "⚠️ Warning Issued",
            EmbedColors.GOLD,
            category="Warning",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Moderator", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Total Warnings", value=str(warning_count), inline=True)
        embed.add_field(name="Reason", value=reason[:500] if reason else "No reason provided", inline=False)
        self._set_user_thumbnail(embed, user)

        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.WARNINGS, embed, view=view, user_id=user.id)

    async def log_warning_removed(
        self: "LoggingService",
        user: discord.User,
        moderator: discord.Member,
        warning_id: int,
        remaining_count: int,
    ) -> None:
        """Log a warning removal."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import UserIdButton, CASE_EMOJI

        logger.tree("Server Logs: log_warning_removed Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Warning ID", str(warning_id)),
            ("Remaining", str(remaining_count)),
        ], emoji="📋")

        embed = self._create_embed(
            "🗑️ Warning Removed",
            EmbedColors.SUCCESS,
            category="Warning",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Removed By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Warning ID", value=f"`#{warning_id}`", inline=True)
        embed.add_field(name="Remaining", value=str(remaining_count), inline=True)
        self._set_user_thumbnail(embed, moderator)

        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            guild_id = self.config.logging_guild_id or case.get('guild_id', 0)
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.WARNINGS, embed, view=view, user_id=user.id)


__all__ = ["WarningsLogsMixin"]
