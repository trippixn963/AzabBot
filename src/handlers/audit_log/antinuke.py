"""
Audit Log Events - Anti-Nuke Mixin
==================================

Routes audit log events to anti-nuke service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger

if TYPE_CHECKING:
    from .cog import AuditLogEvents


class AntiNukeMixin:
    """Mixin for anti-nuke detection routing."""

    async def _check_antinuke(self: "AuditLogEvents", entry: discord.AuditLogEntry) -> None:
        """Route audit log events to anti-nuke service for detection."""
        if not self.bot.antinuke_service:
            return

        if not entry.user_id or not entry.guild:
            return

        try:
            # Track bans
            if entry.action == discord.AuditLogAction.ban:
                await self.bot.antinuke_service.track_ban(entry.guild, entry.user_id)

            # Track kicks
            elif entry.action == discord.AuditLogAction.kick:
                await self.bot.antinuke_service.track_kick(entry.guild, entry.user_id)

            # Track channel deletions
            elif entry.action == discord.AuditLogAction.channel_delete:
                await self.bot.antinuke_service.track_channel_delete(entry.guild, entry.user_id)

            # Track role deletions
            elif entry.action == discord.AuditLogAction.role_delete:
                await self.bot.antinuke_service.track_role_delete(entry.guild, entry.user_id)

        except Exception as e:
            logger.warning(f"Anti-nuke check failed: {e}")


__all__ = ["AntiNukeMixin"]
