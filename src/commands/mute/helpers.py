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
        expires_at: Optional[float],
        reason: Optional[str],
        evidence: Optional[str],
        case_info: Optional[dict],
        is_extension: bool = False,
        xp_lost: Optional[int] = None,
        offense_count: int = 0,
        muted_at: Optional[float] = None,
    ) -> None:
        """Send DM notification to muted user (appeal via tickets, not button)."""
        dm_title = "Your mute has been extended" if is_extension else "You have been muted"

        # Build fields with duration and unmute time
        fields = [("Duration", f"`{duration_display}`", True)]

        # Add XP lost if applicable
        if xp_lost and offense_count > 0:
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(offense_count, f"{offense_count}th")
            fields.append(("XP Lost", f"`-{xp_lost:,}` ({ordinal} offense)", True))

        # Add unmute time in Discord timestamp format (shows in user's timezone)
        if expires_at:
            unmute_ts = int(expires_at)
            fields.append(("Unmutes", f"<t:{unmute_ts}:F> (<t:{unmute_ts}:R>)", False))

        # Add coin unjail cost (for mutes >= 1 hour)
        try:
            from src.services.jawdat_economy import calculate_unjail_cost, COINS_EMOJI_ID
            import time

            # Calculate duration in hours
            if expires_at and muted_at:
                duration_hours = (expires_at - muted_at) / 3600
            elif expires_at:
                duration_hours = (expires_at - time.time()) / 3600
            else:
                # Permanent mute
                duration_hours = 168.0  # 7+ days

            # Only show for mutes >= 1 hour
            if duration_hours >= 1.0:
                # Get offense count for this user
                weekly_offenses = self.bot.db.get_user_mute_count_week(target.id, guild.id)
                if weekly_offenses < 1:
                    weekly_offenses = 1

                unjail_cost, breakdown = calculate_unjail_cost(weekly_offenses, duration_hours)

                cost_text = f"`{unjail_cost:,}` coins"
                if breakdown:
                    cost_text += f"\n-# Base {breakdown['base_cost']:,} × {breakdown['multiplier']} ({breakdown['duration_tier']})"

                fields.append((f"<:coins:{COINS_EMOJI_ID}> Unjail Cost", cost_text, False))

        except Exception as e:
            logger.warning("Failed to calculate unjail cost for DM", [
                ("User", f"{target.name} ({target.id})"),
                ("Error", str(e)[:50]),
            ])

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
            fields=fields,
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

    async def _broadcast_case_event(
        self: "MuteCog",
        case_info: Optional[dict],
        user_id: int,
        moderator_id: int,
        action_type: str,
        reason: Optional[str] = None,
        duration: Optional[str] = None,
        is_extension: bool = False,
    ) -> None:
        """Broadcast case creation event via WebSocket for dashboard updates."""
        if not case_info:
            return
        if not hasattr(self.bot, 'api_service') or not self.bot.api_service:
            return

        await self.bot.api_service.broadcast_case_created({
            'case_id': case_info['case_id'],
            'user_id': user_id,
            'moderator_id': moderator_id,
            'action_type': action_type,
            'reason': reason,
            'duration': duration,
            'is_extension': is_extension,
        })
        await self.bot.api_service.broadcast_stats_updated()

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
