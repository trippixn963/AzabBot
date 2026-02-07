"""
AzabBot - Mutes Handler
=======================

Handles timeout, mute, unmute logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.core.database import get_db
from ..categories import LogCategory
from ..views import ModActionLogView

if TYPE_CHECKING:
    from ..service import LoggingService


class MutesLogsMixin:
    """Mixin for mute/timeout logging."""

    async def log_timeout(
        self: "LoggingService",
        user: discord.Member,
        until: Optional[datetime] = None,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a timeout."""
        if not self._should_log(user.guild.id):
            return

        logger.tree("Server Logs: log_timeout Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})" if moderator else "System"),
            ("Until", str(until) if until else "None"),
            ("Case ID", case_id or "None"),
        ], emoji="📋")

        embed = self._create_embed("⏰ Member Timed Out", EmbedColors.WARNING, category="Timeout", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)

        if until:
            timestamp = int(until.timestamp())
            now = datetime.now(until.tzinfo) if until.tzinfo else datetime.now()
            duration_seconds = int((until - now).total_seconds())
            if duration_seconds > 0:
                if duration_seconds >= 86400:
                    duration_str = f"{duration_seconds // 86400}d {(duration_seconds % 86400) // 3600}h"
                elif duration_seconds >= 3600:
                    duration_str = f"{duration_seconds // 3600}h {(duration_seconds % 3600) // 60}m"
                else:
                    duration_str = f"{duration_seconds // 60}m"
                embed.add_field(name="Duration", value=f"`{duration_str}`", inline=True)
            embed.add_field(name="Expires", value=f"<t:{timestamp}:R>", inline=True)

        # Add prior actions context
        db = get_db()
        counts = db.get_user_case_counts(user.id, user.guild.id)
        if counts["mute_count"] or counts["ban_count"] or counts["warn_count"]:
            prior = f"🔇 `{counts['mute_count']}` mutes · 🔨 `{counts['ban_count']}` bans · ⚠️ `{counts['warn_count']}` warns"
            embed.add_field(name="Prior Actions", value=prior, inline=False)

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, user.guild.id, case_id=case_id)
        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id, view=view)

    async def log_timeout_remove(
        self: "LoggingService",
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a timeout removal."""
        if not self._should_log(user.guild.id):
            return

        logger.tree("Server Logs: log_timeout_remove Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})" if moderator else "System"),
            ("Case ID", case_id or "None"),
        ], emoji="📋")

        embed = self._create_embed("⏰ Timeout Removed", EmbedColors.SUCCESS, category="Timeout Remove", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, user.guild.id, case_id=case_id)
        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id, view=view)

    async def log_mute(
        self: "LoggingService",
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        duration: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a mute (role-based)."""
        if not self._should_log(user.guild.id):
            return

        logger.tree("Server Logs: log_mute Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})" if moderator else "System"),
            ("Duration", duration or "Permanent"),
            ("Case ID", case_id or "None"),
        ], emoji="📋")

        embed = self._create_embed("🔇 Member Muted", EmbedColors.LOG_NEGATIVE, category="Mute", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Duration", value=f"`{duration}`" if duration else "`Permanent`", inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)

        # Add prior actions context
        db = get_db()
        counts = db.get_user_case_counts(user.id, user.guild.id)
        if counts["mute_count"] or counts["ban_count"] or counts["warn_count"]:
            prior = f"🔇 `{counts['mute_count']}` mutes · 🔨 `{counts['ban_count']}` bans · ⚠️ `{counts['warn_count']}` warns"
            embed.add_field(name="Prior Actions", value=prior, inline=False)

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, user.guild.id, case_id=case_id)
        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id, view=view)

    async def log_unmute(
        self: "LoggingService",
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log an unmute (role-based)."""
        if not self._should_log(user.guild.id):
            return

        logger.tree("Server Logs: log_unmute Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})" if moderator else "System"),
            ("Reason", reason or "None"),
            ("Case ID", case_id or "None"),
        ], emoji="📋")

        embed = self._create_embed("🔊 Member Unmuted", EmbedColors.SUCCESS, category="Unmute", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, user.guild.id, case_id=case_id)
        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id, view=view)

    async def log_muted_vc_violation(
        self: "LoggingService",
        member: discord.Member,
        channel_name: str,
        timeout_duration: timedelta,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log when a muted user attempts to join voice and gets timed out."""
        if not self._should_log(member.guild.id):
            return

        logger.tree("Server Logs: log_muted_vc_violation Called", [
            ("Member", f"{member.name} ({member.id})"),
            ("Channel", channel_name),
        ], emoji="📋")

        hours = int(timeout_duration.total_seconds() // 3600)
        timeout_str = f"{hours} hour{'s' if hours != 1 else ''}"

        embed = self._create_embed(
            "🔇 Muted User VC Violation",
            EmbedColors.ERROR,
            category="VC Violation",
            user_id=member.id,
        )
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        channel_value = f"🔊 <#{channel_id}>" if channel_id else f"🔊 {channel_name}"
        embed.add_field(name="Attempted Channel", value=channel_value, inline=True)
        embed.add_field(name="Action", value="Disconnected", inline=True)
        embed.add_field(name="Timeout Applied", value=f"`{timeout_str}`", inline=True)
        embed.add_field(
            name="Reason",
            value="Muted users are not allowed in voice channels",
            inline=False,
        )
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=member.id)
