"""
AzabBot - Warn Helpers
======================

Helper functions for the warn command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.utils.dm_helpers import send_moderation_dm

if TYPE_CHECKING:
    from src.bot import AzabBot


async def send_warn_dm(
    user: discord.User,
    guild: discord.Guild,
    moderator: discord.Member,
    reason: Optional[str],
    evidence: Optional[str],
    active_warns: int,
    total_warns: int,
    avatar_url: str,
) -> None:
    """Send DM notification to warned user."""
    # Build warning count field
    if active_warns != total_warns:
        warn_field = ("Active Warnings", f"`{active_warns}` (`{total_warns}` total)", True)
    else:
        warn_field = ("Warning #", f"`{active_warns}`", True)

    await send_moderation_dm(
        user=user,
        title="You have been warned",
        color=EmbedColors.WARNING,
        guild=guild,
        moderator=moderator,
        reason=reason,
        evidence=evidence,
        thumbnail_url=avatar_url,
        fields=[warn_field],
        context="Warn DM",
    )


async def log_warn_to_tracker(
    bot: "AzabBot",
    moderator: discord.Member,
    target: discord.User,
    reason: Optional[str],
) -> None:
    """Log warn action to mod tracker if moderator is tracked."""
    if bot.mod_tracker and bot.mod_tracker.is_tracked(moderator.id):
        await bot.mod_tracker.log_warn(
            mod=moderator,
            target=target,
            reason=reason,
        )


async def broadcast_case_event(
    bot: "AzabBot",
    case_info: Optional[dict],
    user_id: int,
    moderator_id: int,
    reason: Optional[str] = None,
    active_warns: int = 1,
    total_warns: int = 1,
) -> None:
    """Broadcast case creation event via WebSocket for dashboard updates."""
    if not case_info:
        return
    if not hasattr(bot, 'api_service') or not bot.api_service:
        return

    await bot.api_service.broadcast_case_created({
        'case_id': case_info['case_id'],
        'user_id': user_id,
        'moderator_id': moderator_id,
        'action_type': 'warn',
        'reason': reason,
        'active_warns': active_warns,
        'total_warns': total_warns,
    })
    await bot.api_service.broadcast_stats_updated()


async def post_mod_log(
    bot: "AzabBot",
    action: str,
    user: discord.User,
    moderator: discord.Member,
    reason: Optional[str] = None,
    active_warns: int = 1,
    total_warns: int = 1,
) -> None:
    """Post a warning action to the server logs forum via logging service."""
    if not bot.logging_service:
        return

    try:
        guild = moderator.guild

        if action.lower() == "warn":
            await bot.logging_service.log_warning_issued(
                user=user,
                moderator=moderator,
                reason=reason,
                warning_count=active_warns,
                guild_id=guild.id,
            )
        elif action.lower() == "unwarn":
            await bot.logging_service.log_warning_removed(
                user=user,
                moderator=moderator,
                warning_id=0,  # TODO: pass actual warning ID
                remaining_count=active_warns,
            )
    except Exception as e:
        logger.error("Mod Log Post Failed", [("Error", str(e)[:50])])


__all__ = ["send_warn_dm", "log_warn_to_tracker", "broadcast_case_event", "post_mod_log"]
