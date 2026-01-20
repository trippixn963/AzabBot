"""
Server Logs - Appeals Handler
=============================

Handles appeal logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors
from src.core.database import get_db

if TYPE_CHECKING:
    from ..service import LoggingService


class AppealsLogsMixin:
    """Mixin for appeal logging."""

    async def log_appeal_created(
        self: "LoggingService",
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        reason: Optional[str] = None,
    ) -> None:
        """Log an appeal creation."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import UserIdButton, CASE_EMOJI

        emoji = "🔨" if action_type == "ban" else "🔇"
        embed = self._create_embed(
            f"{emoji} Appeal Created",
            EmbedColors.GOLD,
            category="Appeal",
            user_id=user.id,
        )
        embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=action_type.title(), inline=True)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if reason:
            embed.add_field(name="Appeal Reason", value=reason[:500], inline=False)
        self._set_user_thumbnail(embed, user)

        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{case['guild_id']}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.APPEALS, embed, view=view, user_id=user.id)

    async def log_appeal_approved(
        self: "LoggingService",
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        approved_by: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """Log an appeal approval."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import UserIdButton, CASE_EMOJI

        embed = self._create_embed(
            "✅ Appeal Approved",
            EmbedColors.SUCCESS,
            category="Appeal",
            user_id=user.id,
        )
        embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=action_type.title(), inline=True)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Approved By", value=self._format_user_field(approved_by), inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason[:500], inline=False)
        self._set_user_thumbnail(embed, approved_by)

        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{case['guild_id']}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.APPEALS, embed, view=view, user_id=user.id)

    async def log_appeal_denied(
        self: "LoggingService",
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        denied_by: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """Log an appeal denial."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import UserIdButton, CASE_EMOJI

        embed = self._create_embed(
            "❌ Appeal Denied",
            EmbedColors.LOG_NEGATIVE,
            category="Appeal",
            user_id=user.id,
        )
        embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=action_type.title(), inline=True)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Denied By", value=self._format_user_field(denied_by), inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason[:500], inline=False)
        self._set_user_thumbnail(embed, denied_by)

        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{case['guild_id']}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.APPEALS, embed, view=view, user_id=user.id)


__all__ = ["AppealsLogsMixin"]
