"""
AzabBot - Appeal Helpers Mixin
==============================

Logging helper methods for appeal service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from .service import AppealService


class HelpersMixin:
    """Mixin for appeal logging helpers."""

    async def _log_appeal_created(
        self: "AppealService",
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        reason: str,
    ) -> None:
        """Log appeal creation to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="📝 Appeal Submitted",
                color=EmbedColors.WARNING,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
            embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
            embed.add_field(name="Type", value=action_type.title(), inline=True)
            embed.add_field(
                name="User",
                value=f"{user.mention}\n`{user.id}`",
                inline=True,
            )
            if reason:
                preview = (reason[:100] + "...") if len(reason) > 100 else reason
                embed.add_field(name="Reason Preview", value=f"```{preview}```", inline=False)

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.APPEALS,
                embed,
            )
        except Exception as e:
            logger.debug("Appeal Creation Log Failed", [("Error", str(e)[:50])])

    async def _log_appeal_resolved(
        self: "AppealService",
        appeal_id: str,
        case_id: str,
        user_id: int,
        moderator: discord.Member,
        resolution: str,
        reason: Optional[str],
    ) -> None:
        """Log appeal resolution to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            emoji = "✅" if resolution == "approved" else "❌"
            color = EmbedColors.SUCCESS if resolution == "approved" else EmbedColors.ERROR

            embed = discord.Embed(
                title=f"{emoji} Appeal {resolution.title()}",
                color=color,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
            embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
            embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
            embed.add_field(
                name="Resolved By",
                value=f"{moderator.mention}\n`{moderator.id}`",
                inline=True,
            )
            if reason:
                embed.add_field(name="Reason", value=f"```{reason[:200]}```", inline=False)

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.APPEALS,
                embed,
            )
        except Exception as e:
            logger.debug("Appeal Resolution Log Failed", [("Error", str(e)[:50])])


__all__ = ["HelpersMixin"]
