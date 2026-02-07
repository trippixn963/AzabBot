"""
AzabBot - Moderation Handler
============================

Handles ban, unban, and kick logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.core.database import get_db
from ..categories import LogCategory
from ..views import ModActionLogView

if TYPE_CHECKING:
    from ..service import LoggingService


class ModerationLogsMixin:
    """Mixin for moderation logging (bans, unbans, kicks)."""

    async def log_ban(
        self: "LoggingService",
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a ban."""
        if not self.enabled:
            return

        logger.tree("Server Logs: log_ban Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})" if moderator else "System"),
            ("Case ID", case_id or "None"),
        ], emoji="📋")

        embed = self._create_embed("🔨 Member Banned", EmbedColors.LOG_NEGATIVE, category="Ban", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)

        # Add prior actions context
        if self.config.logging_guild_id:
            db = get_db()
            counts = db.get_user_case_counts(user.id, self.config.logging_guild_id)
            if counts["mute_count"] or counts["ban_count"] or counts["warn_count"]:
                prior = f"🔇 `{counts['mute_count']}` mutes · 🔨 `{counts['ban_count']}` bans · ⚠️ `{counts['warn_count']}` warns"
                embed.add_field(name="Prior Actions", value=prior, inline=False)

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, self.config.logging_guild_id or 0, case_id=case_id)
        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id, view=view)

    async def log_unban(
        self: "LoggingService",
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log an unban."""
        if not self.enabled:
            return

        logger.tree("Server Logs: log_unban Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})" if moderator else "System"),
            ("Case ID", case_id or "None"),
        ], emoji="📋")

        embed = self._create_embed("🔓 Member Unbanned", EmbedColors.SUCCESS, category="Unban", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)
        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, self.config.logging_guild_id or 0, case_id=case_id)
        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id, view=view)

    async def log_kick(
        self: "LoggingService",
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a kick."""
        if not self.enabled:
            return

        logger.tree("Server Logs: log_kick Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})" if moderator else "System"),
            ("Case ID", case_id or "None"),
        ], emoji="📋")

        embed = self._create_embed("👢 Member Kicked", EmbedColors.LOG_NEGATIVE, category="Kick", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)

        # Add prior actions context
        if self.config.logging_guild_id:
            db = get_db()
            counts = db.get_user_case_counts(user.id, self.config.logging_guild_id)
            if counts["mute_count"] or counts["ban_count"] or counts["warn_count"]:
                prior = f"🔇 `{counts['mute_count']}` mutes · 🔨 `{counts['ban_count']}` bans · ⚠️ `{counts['warn_count']}` warns"
                embed.add_field(name="Prior Actions", value=prior, inline=False)

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, self.config.logging_guild_id or 0, case_id=case_id)
        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id, view=view)
