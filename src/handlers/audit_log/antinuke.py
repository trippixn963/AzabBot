"""
AzabBot - Anti-Nuke Mixin
=========================

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

            # Track bot additions
            elif entry.action == discord.AuditLogAction.bot_add:
                # entry.target is the bot that was added
                if entry.target and isinstance(entry.target, discord.Member):
                    await self.bot.antinuke_service.track_bot_add(
                        entry.guild,
                        entry.user_id,
                        entry.target,
                    )

            # Track role permission changes (escalation detection)
            elif entry.action == discord.AuditLogAction.role_update:
                await self._check_permission_escalation(entry)

        except Exception as e:
            logger.warning("Anti-Nuke Check Failed", [("Error", str(e)[:50])])

    async def _check_permission_escalation(
        self: "AuditLogEvents",
        entry: discord.AuditLogEntry,
    ) -> None:
        """Check if a role update involves permission escalation."""
        if not self.bot.antinuke_service:
            return

        # Get the role that was updated
        if not entry.target or not isinstance(entry.target, discord.Role):
            return

        # Check if permissions were changed
        before = entry.before
        after = entry.after

        if not hasattr(before, "permissions") or not hasattr(after, "permissions"):
            return

        before_perms = before.permissions
        after_perms = after.permissions

        # Only check if permissions actually changed
        if before_perms == after_perms:
            return

        await self.bot.antinuke_service.track_permission_change(
            entry.guild,
            entry.user_id,
            entry.target,
            before_perms,
            after_perms,
        )


__all__ = ["AntiNukeMixin"]
