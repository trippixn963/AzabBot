"""
AzabBot - Audit Handler
=======================

Handles raw audit log logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors
from ..categories import LogCategory

if TYPE_CHECKING:
    from ..service import LoggingService


class AuditLogsMixin:
    """Mixin for raw audit log logging."""

    async def log_audit_raw(
        self: "LoggingService",
        action: str,
        user: Optional[discord.User],
        target: Optional[discord.User],
        details: str,
        audit_id: Optional[int] = None,
    ) -> None:
        """Log an uncategorized audit log event."""
        if not self.enabled:
            return

        embed = self._create_embed(
            f"🔍 {action}",
            EmbedColors.BLUE,
            category="Audit",
            user_id=user.id if user else None,
        )
        if user:
            embed.add_field(name="Actor", value=self._format_user_field(user), inline=True)
        if target:
            embed.add_field(name="Target", value=self._format_user_field(target), inline=True)
        if audit_id:
            embed.add_field(name="Audit ID", value=f"`{audit_id}`", inline=True)
        embed.add_field(name="Details", value=details[:1000], inline=False)
        if user:
            self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.AUDIT_RAW, embed, user_id=user.id if user else None)


__all__ = ["AuditLogsMixin"]
