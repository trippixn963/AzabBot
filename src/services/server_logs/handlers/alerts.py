"""
Server Logs - Alerts Handler
============================

Handles raid detection and lockdown logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, List, Optional

import discord

from src.core.config import EmbedColors
from src.core.logger import logger

if TYPE_CHECKING:
    from ..service import LoggingService


class AlertsLogsMixin:
    """Mixin for alert and lockdown logging."""

    async def log_raid_alert(
        self: "LoggingService",
        join_count: int,
        time_window: int,
        recent_members: List[discord.Member],
    ) -> None:
        """Log a potential raid alert."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        logger.tree("Server Logs: log_raid_alert Called", [
            ("Join Count", str(join_count)),
            ("Time Window", f"{time_window}s"),
            ("Recent Members", str(len(recent_members))),
        ], emoji="🚨")

        embed = self._create_embed("🚨 POTENTIAL RAID DETECTED", EmbedColors.LOG_NEGATIVE, category="Raid Alert")
        embed.add_field(
            name="Joins Detected",
            value=f"**{join_count}** members in **{time_window}** seconds",
            inline=False,
        )

        if recent_members:
            members_list = []
            for member in recent_members[:10]:
                created = int(member.created_at.timestamp())
                members_list.append(f"{member.mention} - Account: <t:{created}:R>")

            if len(recent_members) > 10:
                members_list.append(f"*...and {len(recent_members) - 10} more*")

            embed.add_field(
                name="Recent Joins",
                value="\n".join(members_list),
                inline=False,
            )

        embed.add_field(
            name="⚠️ Recommended Actions",
            value="• Enable verification level\n• Check member accounts\n• Consider lockdown if malicious",
            inline=False,
        )

        await self._send_log(LogCategory.ALERTS, embed)

    async def log_lockdown(
        self: "LoggingService",
        moderator: discord.Member,
        reason: Optional[str],
        channel_count: int,
        action: str,
    ) -> None:
        """Log a server lockdown or unlock action."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        logger.tree("Server Logs: log_lockdown Called", [
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Action", action),
            ("Channels", str(channel_count)),
        ], emoji="🔒")

        if action == "lock":
            embed = self._create_embed("🔒 SERVER LOCKED", EmbedColors.LOG_NEGATIVE, category="Lockdown")
            embed.add_field(name="Status", value="**All channels locked**", inline=False)
        else:
            embed = self._create_embed("🔓 SERVER UNLOCKED", EmbedColors.SUCCESS, category="Lockdown")
            embed.add_field(name="Status", value="**All channels restored**", inline=False)

        embed.add_field(name="By", value=moderator.mention, inline=True)
        embed.add_field(name="Channels", value=f"`{channel_count}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        await self._send_log(LogCategory.ALERTS, embed)

        if action == "lock" and self.config.developer_id:
            thread = self._threads.get(LogCategory.ALERTS)
            if thread:
                await thread.send(f"<@{self.config.developer_id}> ⚠️ **Server lockdown initiated**")

    async def log_auto_lockdown(
        self: "LoggingService",
        join_count: int,
        time_window: int,
        auto_unlock_in: int,
    ) -> None:
        """Log an automatic raid lockdown."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🚨 AUTO-LOCKDOWN TRIGGERED", 0xFF0000, category="Lockdown")
        embed.add_field(name="Status", value="**Server automatically locked - RAID DETECTED**", inline=False)
        embed.add_field(name="Trigger", value=f"`{join_count}` joins in `{time_window}s`", inline=True)
        embed.add_field(name="Auto-Unlock", value=f"In `{auto_unlock_in}s`", inline=True)
        embed.add_field(name="Action", value="Use `/unlock` to unlock manually", inline=False)

        await self._send_log(LogCategory.ALERTS, embed)

        if self.config.developer_id:
            thread = self._threads.get(LogCategory.ALERTS)
            if thread:
                await thread.send(
                    f"<@{self.config.developer_id}> 🚨 **RAID DETECTED - AUTO-LOCKDOWN TRIGGERED!**\n"
                    f"Detected {join_count} joins in {time_window}s. Auto-unlock in {auto_unlock_in}s."
                )

    async def log_auto_unlock(self: "LoggingService") -> None:
        """Log an automatic unlock after raid lockdown expires."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🔓 AUTO-UNLOCK", EmbedColors.SUCCESS, category="Lockdown")
        embed.add_field(name="Status", value="**Raid lockdown has expired**", inline=False)
        embed.add_field(name="Action", value="Server permissions restored automatically", inline=False)

        await self._send_log(LogCategory.ALERTS, embed)


__all__ = ["AlertsLogsMixin"]
