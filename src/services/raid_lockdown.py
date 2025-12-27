"""
Azab Discord Bot - Auto Raid Lockdown Service
==============================================

Automatically locks server when raid is detected.

DESIGN:
    Integrates with existing raid detection in bot.py.
    When raid threshold is reached, automatically triggers lockdown.
    Auto-unlocks after configurable duration.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Auto-unlock duration (seconds)
AUTO_UNLOCK_DURATION = 300  # 5 minutes

# Cooldown between auto-lockdowns (prevent spam)
LOCKDOWN_COOLDOWN = 600  # 10 minutes


# =============================================================================
# Raid Lockdown Service
# =============================================================================

class RaidLockdownService:
    """
    Automatically locks server when raid is detected.

    Works with existing raid detection in bot.py.
    """

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # Cooldown tracking
        self._last_auto_lockdown: Optional[datetime] = None
        self._auto_unlock_task: Optional[asyncio.Task] = None

        logger.tree("Raid Lockdown Service Loaded", [
            ("Auto-Unlock", f"{AUTO_UNLOCK_DURATION}s"),
            ("Cooldown", f"{LOCKDOWN_COOLDOWN}s"),
        ], emoji="🚨")

    async def trigger_raid_lockdown(
        self,
        guild: discord.Guild,
        join_count: int,
        time_window: int,
    ) -> bool:
        """
        Trigger automatic lockdown due to raid.

        Returns True if lockdown was triggered.
        """
        # Check cooldown
        if self._last_auto_lockdown:
            elapsed = (datetime.now(NY_TZ) - self._last_auto_lockdown).total_seconds()
            if elapsed < LOCKDOWN_COOLDOWN:
                logger.debug(f"Raid lockdown on cooldown ({int(LOCKDOWN_COOLDOWN - elapsed)}s remaining)")
                return False

        # Check if already locked
        if self.db.is_locked(guild.id):
            logger.debug("Server already locked, skipping auto-lockdown")
            return False

        # Get @everyone role
        everyone_role = guild.default_role
        original_perms = everyone_role.permissions

        # Save original permissions
        self.db.save_lockdown_permissions(
            guild_id=guild.id,
            send_messages=original_perms.send_messages,
            connect=original_perms.connect,
            add_reactions=original_perms.add_reactions,
            create_public_threads=original_perms.create_public_threads,
            create_private_threads=original_perms.create_private_threads,
            send_messages_in_threads=original_perms.send_messages_in_threads,
        )

        try:
            # Create new permissions with messaging disabled
            new_perms = discord.Permissions(original_perms.value)
            new_perms.update(
                send_messages=False,
                connect=False,
                add_reactions=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
            )

            # Apply lockdown
            await everyone_role.edit(
                permissions=new_perms,
                reason=f"AUTO-LOCKDOWN: Raid detected ({join_count} joins in {time_window}s)",
            )

            # Save lockdown state (use bot ID as locker)
            self.db.start_lockdown(
                guild_id=guild.id,
                locked_by=self.bot.user.id if self.bot.user else 0,
                reason=f"Raid detected: {join_count} joins in {time_window}s",
                channel_count=len(guild.channels),
            )

            # Update cooldown
            self._last_auto_lockdown = datetime.now(NY_TZ)

            logger.tree("AUTO-LOCKDOWN TRIGGERED", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Reason", f"{join_count} joins in {time_window}s"),
                ("Auto-Unlock", f"In {AUTO_UNLOCK_DURATION}s"),
            ], emoji="🚨")

            # Log to server logs
            if self.bot.logging_service and self.bot.logging_service.enabled:
                await self.bot.logging_service.log_auto_lockdown(
                    join_count=join_count,
                    time_window=time_window,
                    auto_unlock_in=AUTO_UNLOCK_DURATION,
                )

            # Send public announcement
            await self._send_lockdown_announcement(guild, join_count, time_window)

            # Alert developer
            await self._alert_mods(guild, join_count, time_window)

            # Schedule auto-unlock
            if self._auto_unlock_task and not self._auto_unlock_task.done():
                self._auto_unlock_task.cancel()
            self._auto_unlock_task = asyncio.create_task(
                self._auto_unlock(guild)
            )

            return True

        except discord.Forbidden:
            logger.warning("Cannot trigger auto-lockdown - missing permissions")
            self.db.clear_lockdown_permissions(guild.id)
            return False
        except discord.HTTPException as e:
            logger.warning(f"Auto-lockdown failed: {e}")
            self.db.clear_lockdown_permissions(guild.id)
            return False

    async def _auto_unlock(self, guild: discord.Guild) -> None:
        """Auto-unlock server after duration."""
        try:
            await asyncio.sleep(AUTO_UNLOCK_DURATION)

            # Verify still locked
            if not self.db.is_locked(guild.id):
                return

            everyone_role = guild.default_role

            # Get saved permissions
            saved_perms = self.db.get_lockdown_permissions(guild.id)
            if not saved_perms:
                saved_perms = {
                    "send_messages": True,
                    "connect": True,
                    "add_reactions": True,
                    "create_public_threads": True,
                    "create_private_threads": True,
                    "send_messages_in_threads": True,
                }

            # Restore permissions
            new_perms = discord.Permissions(everyone_role.permissions.value)
            new_perms.update(
                send_messages=saved_perms.get("send_messages", True),
                connect=saved_perms.get("connect", True),
                add_reactions=saved_perms.get("add_reactions", True),
                create_public_threads=saved_perms.get("create_public_threads", True),
                create_private_threads=saved_perms.get("create_private_threads", True),
                send_messages_in_threads=saved_perms.get("send_messages_in_threads", True),
            )

            await everyone_role.edit(
                permissions=new_perms,
                reason="AUTO-UNLOCK: Raid lockdown expired",
            )

            # Clear lockdown state
            self.db.end_lockdown(guild.id)

            logger.tree("AUTO-UNLOCK COMPLETE", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Duration", f"{AUTO_UNLOCK_DURATION}s"),
            ], emoji="🔓")

            # Send public announcement
            await self._send_unlock_announcement(guild)

            # Log to server logs
            if self.bot.logging_service and self.bot.logging_service.enabled:
                await self.bot.logging_service.log_auto_unlock()

        except asyncio.CancelledError:
            logger.debug("Auto-unlock task cancelled (manual unlock)")
        except Exception as e:
            logger.warning(f"Auto-unlock failed: {e}")

    async def _send_lockdown_announcement(
        self,
        guild: discord.Guild,
        join_count: int,
        time_window: int,
    ) -> None:
        """Send lockdown announcement to general channel."""
        if not self.config.general_channel_id:
            return

        channel = guild.get_channel(self.config.general_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="🚨 AUTOMATIC LOCKDOWN",
            description=(
                "**A raid has been detected.**\n"
                "The server has been automatically locked to protect members.\n\n"
                f"Detected: `{join_count}` accounts joined in `{time_window}` seconds"
            ),
            color=0xFF0000,  # Red
            timestamp=datetime.now(NY_TZ),
        )
        embed.add_field(
            name="Auto-Unlock",
            value=f"<t:{int(datetime.now(NY_TZ).timestamp()) + AUTO_UNLOCK_DURATION}:R>",
            inline=True,
        )
        embed.add_field(
            name="Manual Unlock",
            value="Moderators can use `/unlock`",
            inline=True,
        )
        set_footer(embed)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _send_unlock_announcement(self, guild: discord.Guild) -> None:
        """Send unlock announcement to general channel."""
        if not self.config.general_channel_id:
            return

        channel = guild.get_channel(self.config.general_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="🔓 Lockdown Lifted",
            description=(
                "The automatic lockdown has expired.\n"
                "You may now resume normal activity."
            ),
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )
        set_footer(embed)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _alert_mods(
        self,
        guild: discord.Guild,
        join_count: int,
        time_window: int,
    ) -> None:
        """Alert mods in general channel about the raid."""
        if not self.config.alert_channel_id:
            return

        try:
            alert_channel = self.bot.get_channel(self.config.alert_channel_id)
            if not alert_channel:
                return

            embed = discord.Embed(
                title="🚨 RAID AUTO-LOCKDOWN TRIGGERED",
                description=f"Server **{guild.name}** has been automatically locked.",
                color=0xFF0000,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Detected", value=f"`{join_count}` joins in `{time_window}s`", inline=True)
            embed.add_field(name="Auto-Unlock", value=f"In `{AUTO_UNLOCK_DURATION}s`", inline=True)
            set_footer(embed)

            instructions = (
                f"@everyone 🚨 **RAID DETECTED - SERVER LOCKED!**\n\n"
                f"**What happened:**\n"
                f"• Detected `{join_count}` accounts joining in `{time_window}` seconds\n"
                f"• Bot automatically **locked the server** (disabled messaging & voice)\n"
                f"• Server will auto-unlock in `{AUTO_UNLOCK_DURATION // 60}` minutes\n\n"
                f"**What mods should do:**\n"
                f"1. Check the new members who joined during the raid\n"
                f"2. Ban any obvious raid/bot accounts\n"
                f"3. Use `/unlock` if you want to unlock early\n"
                f"4. Consider increasing server verification level temporarily"
            )

            await alert_channel.send(content=instructions, embed=embed)
        except discord.HTTPException:
            pass

    def cancel_auto_unlock(self) -> None:
        """Cancel pending auto-unlock (called when manual unlock happens)."""
        if self._auto_unlock_task and not self._auto_unlock_task.done():
            self._auto_unlock_task.cancel()
            self._auto_unlock_task = None


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["RaidLockdownService"]
