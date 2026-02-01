"""
AzabBot - Bulk Detection Mixin
==============================

Bulk action detection and alert sending.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ

from .constants import (
    BULK_ACTION_WINDOW,
    BULK_BAN_THRESHOLD,
    BULK_DELETE_THRESHOLD,
    BULK_TIMEOUT_THRESHOLD,
    PRIORITY_CRITICAL,
)

if TYPE_CHECKING:
    from .service import ModTrackerService


class BulkDetectionMixin:
    """Mixin for bulk action detection and alerts."""

    def _record_action(self: "ModTrackerService", mod_id: int, action_type: str) -> None:
        """
        Record an action for bulk detection and update last activity.

        Args:
            mod_id: The moderator's ID.
            action_type: Type of action (ban, timeout, delete, etc.)
        """
        now = datetime.now(NY_TZ)

        # Update last action time
        self._last_action[mod_id] = now

        # Record for bulk detection
        self._action_history[mod_id][action_type].append(now)

        # Clean old entries outside the window
        cutoff = now - timedelta(seconds=BULK_ACTION_WINDOW)
        self._action_history[mod_id][action_type] = [
            t for t in self._action_history[mod_id][action_type]
            if t > cutoff
        ]

    async def _check_bulk_action(
        self: "ModTrackerService",
        mod_id: int,
        action_type: str
    ) -> None:
        """
        Check if bulk action threshold exceeded, send alert, and remove mod role.

        Args:
            mod_id: The moderator's ID.
            action_type: Type of action to check.
        """
        count = len(self._action_history[mod_id][action_type])

        threshold = None
        if action_type == "ban":
            threshold = BULK_BAN_THRESHOLD
        elif action_type == "timeout":
            threshold = BULK_TIMEOUT_THRESHOLD
        elif action_type == "delete":
            threshold = BULK_DELETE_THRESHOLD

        if threshold and count >= threshold:
            # Remove mod role first
            role_removed, member = await self._remove_mod_role(mod_id)

            # Send alert to mod tracker thread
            description = f"**{count}** {action_type}s in the last 5 minutes"
            if role_removed:
                description += "\n\n**Mod role has been automatically removed.**"

            await self._send_alert(
                mod_id=mod_id,
                alert_type="Bulk Action Detected",
                description=description,
                color=EmbedColors.ERROR,
            )

            # Send @everyone alert to alert channel
            if role_removed and member:
                await self._send_bulk_action_public_alert(member, action_type, count, threshold)

            # Clear after alerting to avoid spam
            self._action_history[mod_id][action_type].clear()

    async def _remove_mod_role(self: "ModTrackerService", mod_id: int) -> tuple:
        """
        Remove the mod role from a user.

        Args:
            mod_id: The moderator's ID.

        Returns:
            Tuple of (success: bool, member: Optional[discord.Member])
        """
        if not self.config.moderation_role_id:
            return False, None

        try:
            # Mod role is in main server
            main_guild_id = self.config.logging_guild_id or self.config.mod_server_id
            guild = self.bot.get_guild(main_guild_id)
            if not guild:
                return False, None

            member = guild.get_member(mod_id)
            if not member:
                return False, None

            role = guild.get_role(self.config.moderation_role_id)
            if not role:
                return False, None

            await member.remove_roles(role, reason="Bulk action detected - automatic removal")

            logger.tree("Mod Tracker: Mod Role Removed", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(mod_id)),
                ("Reason", "Bulk action detected"),
            ], emoji="🚨")

            return True, member

        except discord.Forbidden:
            logger.error("Mod Tracker: No Permission To Remove Role", [
                ("Mod ID", str(mod_id)),
            ])
            return False, None
        except Exception as e:
            logger.error("Mod Tracker: Failed To Remove Role", [
                ("Mod ID", str(mod_id)),
                ("Error", str(e)[:50]),
            ])
            return False, None

    async def _send_bulk_action_public_alert(
        self: "ModTrackerService",
        member: discord.Member,
        action_type: str,
        count: int,
        threshold: int,
    ) -> None:
        """
        Send a public alert to the alert channel when mod role is removed.

        Args:
            member: The moderator who had their role removed.
            action_type: Type of action (ban, timeout, delete).
            count: Number of actions performed.
            threshold: The threshold that was exceeded.
        """
        if not self.config.alert_channel_id:
            return

        try:
            alert_channel = self.bot.get_channel(self.config.alert_channel_id)
            if not alert_channel:
                return

            # Format action type for display
            action_display = {
                "ban": "Mass Bans",
                "timeout": "Mass Timeouts",
                "delete": "Mass Deletes",
            }.get(action_type, action_type.title())

            # Build embed
            embed = discord.Embed(
                title="🚨 MOD ROLE AUTOMATICALLY REMOVED",
                color=EmbedColors.ERROR,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Moderator", value=f"{member.mention}\n`{member.name}`", inline=True)
            embed.add_field(name="Action", value=action_display, inline=True)
            embed.add_field(name="Count", value=f"`{count}` in 5 min\n(Threshold: `{threshold}`)", inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="Mod Tracker • Bulk Action Protection")

            # Build message content
            instructions = (
                f"@everyone 🚨 **MOD ROLE AUTOMATICALLY REMOVED**\n\n"
                f"**What happened:**\n"
                f"• {member.mention} ({member.name}) performed **{count} {action_type}s** in 5 minutes\n"
                f"• This exceeded the safety threshold of `{threshold}`\n"
                f"• Bot automatically **removed their mod role** as a precaution\n\n"
                f"**What to do:**\n"
                f"1. Check if this was legitimate moderation (e.g., raid response)\n"
                f"2. If legitimate, restore their mod role manually\n"
                f"3. If suspicious, investigate their recent actions"
            )

            await alert_channel.send(content=instructions, embed=embed)

            logger.tree("Mod Tracker: Bulk Action Alert Sent", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Action", action_type),
                ("Count", str(count)),
            ], emoji="🚨")

        except Exception as e:
            logger.error("Mod Tracker: Failed To Send Bulk Action Alert", [
                ("Mod ID", str(member.id)),
                ("Error", str(e)[:50]),
            ])

    async def _send_alert(
        self: "ModTrackerService",
        mod_id: int,
        alert_type: str,
        description: str,
        color: int = EmbedColors.WARNING,
        priority: int = PRIORITY_CRITICAL,
        ping_owner: bool = True,
    ) -> None:
        """
        Send an alert to a mod's thread with optional ping via priority queue.

        Security alerts are sent with PRIORITY_CRITICAL to ensure they
        are processed before regular logs during mass events/raids.

        Args:
            mod_id: The moderator's ID.
            alert_type: Type of alert for the title.
            description: Alert description.
            color: Embed color.
            priority: Queue priority (default CRITICAL).
            ping_owner: Whether to ping the owner (default True).
        """
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return

        embed = discord.Embed(
            title=f"⚠️ {alert_type}",
            description=description,
            color=color,
            timestamp=datetime.now(NY_TZ),
        )
        embed.set_footer(text=f"Alert • Mod ID: {mod_id}")

        # Queue with high priority - alerts bypass regular log queue
        await self._enqueue(
            thread_id=tracked["thread_id"],
            embed=embed,
            priority=priority,
            content=f"<@{self.config.owner_id}>" if ping_owner else None,
            is_alert=True,
        )

        logger.tree("Mod Tracker: Alert Queued", [
            ("Mod ID", str(mod_id)),
            ("Type", alert_type),
            ("Priority", "CRITICAL" if priority == PRIORITY_CRITICAL else "HIGH"),
        ], emoji="⚠️")


__all__ = ["BulkDetectionMixin"]
