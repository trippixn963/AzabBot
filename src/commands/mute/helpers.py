"""
AzabBot - Helpers Mixin
=======================

Helper methods for DM notifications and logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.utils.dm_helpers import send_moderation_dm

if TYPE_CHECKING:
    from .cog import MuteCog


class HelpersMixin:
    """Mixin for mute helper methods."""

    async def _send_mute_dm(
        self: "MuteCog",
        target: discord.Member,
        guild: discord.Guild,
        moderator: discord.Member,
        duration_display: str,
        duration_seconds: Optional[int],
        reason: Optional[str],
        evidence: Optional[str],
        case_info: Optional[dict],
        is_extension: bool = False,
    ) -> None:
        """Send DM notification to muted user (appeal via tickets, not button)."""
        dm_title = "Your mute has been extended" if is_extension else "You have been muted"

        # Note: Mute appeals are handled through server tickets, not appeal button
        sent = await send_moderation_dm(
            user=target,
            title=dm_title,
            color=EmbedColors.ERROR,
            guild=guild,
            moderator=moderator,
            reason=reason,
            evidence=evidence,
            thumbnail_url=target.display_avatar.url,
            fields=[("Duration", f"`{duration_display}`", True)],
            view=None,
            context="Mute DM",
        )

        if case_info:
            logger.tree("Mute DM Sent", [
                ("User", target.name),
                ("ID", str(target.id)),
                ("Case", case_info["case_id"]),
                ("Delivered", "Yes" if sent else "No (DMs disabled)"),
            ], emoji="📨")

    async def _send_unmute_dm(
        self: "MuteCog",
        target: discord.Member,
        guild: discord.Guild,
        moderator: discord.Member,
        reason: Optional[str],
    ) -> None:
        """Send DM notification to unmuted user."""
        await send_moderation_dm(
            user=target,
            title="You have been unmuted",
            color=EmbedColors.SUCCESS,
            guild=guild,
            moderator=moderator,
            reason=reason,
            thumbnail_url=target.display_avatar.url,
            context="Unmute DM",
        )

    async def _log_mute_to_tracker(
        self: "MuteCog",
        moderator: discord.Member,
        target: discord.Member,
        duration: str,
        reason: Optional[str],
        case_id: Optional[int],
    ) -> None:
        """Log mute action to mod tracker if moderator is tracked."""
        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(moderator.id):
            await self.bot.mod_tracker.log_mute(
                mod=moderator,
                target=target,
                duration=duration,
                reason=reason,
                case_id=case_id,
            )

    async def _log_unmute_to_tracker(
        self: "MuteCog",
        moderator: discord.Member,
        target: discord.Member,
        reason: Optional[str],
        case_id: Optional[int],
    ) -> None:
        """Log unmute action to mod tracker if moderator is tracked."""
        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(moderator.id):
            await self.bot.mod_tracker.log_unmute(
                mod=moderator,
                target=target,
                reason=reason,
                case_id=case_id,
            )

    async def _post_mod_log(
        self: "MuteCog",
        action: str,
        user: discord.Member,
        moderator: discord.Member,
        reason: Optional[str] = None,
        duration: Optional[str] = None,
        color: int = EmbedColors.INFO,
    ) -> None:
        """
        Post an action to the server logs forum via logging service.

        Args:
            action: Action name (Mute/Unmute).
            user: Target user.
            moderator: Moderator who performed action.
            reason: Optional reason.
            duration: Optional duration string (unused, kept for compatibility).
            color: Embed color (unused, kept for compatibility).
        """
        if not self.bot.logging_service:
            return

        try:
            if action.lower() == "mute":
                await self.bot.logging_service.log_mute(
                    user=user,
                    moderator=moderator,
                    reason=reason,
                    duration=duration,
                )
            elif action.lower() == "unmute":
                await self.bot.logging_service.log_unmute(
                    user=user,
                    moderator=moderator,
                    reason=reason,
                )
        except Exception as e:
            logger.error("Failed to Post Mod Log", [
                ("Action", action),
                ("Error", str(e)[:50]),
            ])


__all__ = ["HelpersMixin"]
