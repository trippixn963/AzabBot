"""
AzabBot - Invites Handler
=========================

Handles invite logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class InvitesLogsMixin:
    """Mixin for invite logging."""

    async def log_invite_create(
        self: "LoggingService",
        invite: discord.Invite,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an invite being created."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🔗 Invite Created", EmbedColors.SUCCESS, category="Invite Create")
        embed.add_field(name="Code", value=f"`{invite.code}`", inline=True)

        if invite.channel:
            embed.add_field(name="Channel", value=self._format_channel(invite.channel), inline=True)

        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        elif invite.inviter:
            embed.add_field(name="By", value=self._format_user_field(invite.inviter), inline=True)

        if invite.max_uses:
            embed.add_field(name="Max Uses", value=str(invite.max_uses), inline=True)
        else:
            embed.add_field(name="Max Uses", value="Unlimited", inline=True)

        if invite.max_age:
            if invite.max_age >= 86400:
                days = invite.max_age // 86400
                expiry = f"{days} day{'s' if days > 1 else ''}"
            elif invite.max_age >= 3600:
                hours = invite.max_age // 3600
                expiry = f"{hours} hour{'s' if hours > 1 else ''}"
            else:
                minutes = invite.max_age // 60
                expiry = f"{minutes} minute{'s' if minutes > 1 else ''}"
            embed.add_field(name="Expires In", value=expiry, inline=True)
        else:
            embed.add_field(name="Expires", value="Never", inline=True)

        if invite.temporary:
            embed.add_field(name="Temporary", value="Yes (kicks on disconnect)", inline=True)

        await self._send_log(LogCategory.INVITES, embed)

    async def log_invite_delete(
        self: "LoggingService",
        invite_code: str,
        channel_name: str,
        uses: Optional[int] = None,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log an invite being deleted."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🔗 Invite Deleted", EmbedColors.LOG_NEGATIVE, category="Invite Delete")
        embed.add_field(name="Code", value=f"`{invite_code}`", inline=True)
        channel_value = f"<#{channel_id}>" if channel_id else f"`{channel_name}`"
        embed.add_field(name="Channel", value=channel_value, inline=True)

        if uses is not None:
            embed.add_field(name="Times Used", value=str(uses), inline=True)

        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.INVITES, embed)


__all__ = ["InvitesLogsMixin"]
