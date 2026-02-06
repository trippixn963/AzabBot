"""
AzabBot - Auto Raid Lockdown Service
====================================

Automatically locks server when raid is detected.

Features:
- Channel-by-channel permission overwrites
- Concurrent channel locking for speed
- Auto-unlock after configurable duration
- Cooldown between lockdowns
- Comprehensive logging and error handling

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Tuple, List, Dict, Any

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.constants import (
    AUTO_UNLOCK_DURATION,
    LOCKDOWN_COOLDOWN,
    DELETE_AFTER_EXTENDED,
)
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.async_utils import create_safe_task
from src.utils.discord_rate_limit import log_http_error

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.core.config import Config
    from src.core.database.manager import DatabaseManager


# =============================================================================
# Constants
# =============================================================================

# Maximum concurrent channel operations
MAX_CONCURRENT_OPS: int = 10


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class LockdownResult:
    """Result of a lockdown/unlock operation."""
    success_count: int = 0
    failed_count: int = 0
    errors: List[str] = field(default_factory=list)


# =============================================================================
# Raid Lockdown Service
# =============================================================================

class RaidLockdownService:
    """
    Automatically locks server when raid is detected.

    Works with existing raid detection in bot.py.
    Uses channel-by-channel permission overwrites for reliability.
    """

    def __init__(self, bot: "AzabBot") -> None:
        self.bot: "AzabBot" = bot
        self.config: "Config" = get_config()
        self.db: "DatabaseManager" = get_db()

        # Cooldown tracking
        self._last_auto_lockdown: Optional[datetime] = None
        self._auto_unlock_task: Optional[asyncio.Task] = None

        logger.tree("Raid Lockdown Service Loaded", [
            ("Auto-Unlock", f"{AUTO_UNLOCK_DURATION}s"),
            ("Cooldown", f"{LOCKDOWN_COOLDOWN}s"),
            ("Max Concurrent", str(MAX_CONCURRENT_OPS)),
        ], emoji="🔒")

    # =========================================================================
    # Channel Lock/Unlock Helpers
    # =========================================================================

    async def _lock_text_channel(
        self,
        channel: discord.TextChannel,
        everyone_role: discord.Role,
        mod_role: Optional[discord.Role],
        reason: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Lock a single text channel.

        Args:
            channel: The text channel to lock.
            everyone_role: The @everyone role.
            mod_role: The moderation role (or None).
            reason: Audit log reason.

        Returns:
            Tuple of (success, error_message).
        """
        try:
            current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

            # Save original permission state
            self.db.save_channel_permission(
                guild_id=channel.guild.id,
                channel_id=channel.id,
                channel_type="text",
                send_messages=current_overwrite.send_messages,
                connect=None,
            )

            # Set overwrite to deny messaging
            current_overwrite.send_messages = False
            current_overwrite.add_reactions = False
            current_overwrite.create_public_threads = False
            current_overwrite.create_private_threads = False
            current_overwrite.send_messages_in_threads = False

            await channel.set_permissions(
                everyone_role,
                overwrite=current_overwrite,
                reason=reason,
            )

            # Give mod role explicit allow so they can still communicate
            if mod_role:
                mod_overwrite: discord.PermissionOverwrite = channel.overwrites_for(mod_role)
                mod_overwrite.send_messages = True
                mod_overwrite.add_reactions = True
                await channel.set_permissions(
                    mod_role,
                    overwrite=mod_overwrite,
                    reason=f"{reason} (mod access)",
                )

            logger.debug("Auto-Lock Channel", [
                ("Channel", f"#{channel.name}"),
                ("ID", str(channel.id)),
            ])

            return True, None

        except discord.Forbidden:
            error_msg = f"#{channel.name}: Missing permissions"
            logger.warning("Auto-Lock Channel Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", "Forbidden"),
            ])
            return False, error_msg

        except discord.HTTPException as e:
            error_msg = f"#{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
            log_http_error(e, "Auto-Lock Text Channel", [
                ("Channel", f"#{channel.name} ({channel.id})"),
            ])
            return False, error_msg

        except Exception as e:
            error_msg = f"#{channel.name}: {str(e)[:LOG_TRUNCATE_SHORT]}"
            logger.error("Auto-Lock Channel Error", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                ("Type", type(e).__name__),
            ])
            return False, error_msg

    async def _lock_voice_channel(
        self,
        channel: discord.VoiceChannel,
        everyone_role: discord.Role,
        mod_role: Optional[discord.Role],
        reason: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Lock a single voice channel.

        Args:
            channel: The voice channel to lock.
            everyone_role: The @everyone role.
            mod_role: The moderation role (or None).
            reason: Audit log reason.

        Returns:
            Tuple of (success, error_message).
        """
        try:
            current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

            self.db.save_channel_permission(
                guild_id=channel.guild.id,
                channel_id=channel.id,
                channel_type="voice",
                send_messages=None,
                connect=current_overwrite.connect,
            )

            current_overwrite.connect = False
            current_overwrite.speak = False

            await channel.set_permissions(
                everyone_role,
                overwrite=current_overwrite,
                reason=reason,
            )

            # Give mod role explicit allow so they can still use voice
            if mod_role:
                mod_overwrite: discord.PermissionOverwrite = channel.overwrites_for(mod_role)
                mod_overwrite.connect = True
                mod_overwrite.speak = True
                await channel.set_permissions(
                    mod_role,
                    overwrite=mod_overwrite,
                    reason=f"{reason} (mod access)",
                )

            logger.debug("Auto-Lock Channel", [
                ("Channel", f"🔊{channel.name}"),
                ("ID", str(channel.id)),
            ])

            return True, None

        except discord.Forbidden:
            error_msg = f"🔊{channel.name}: Missing permissions"
            logger.warning("Auto-Lock Channel Failed", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", "Forbidden"),
            ])
            return False, error_msg

        except discord.HTTPException as e:
            error_msg = f"🔊{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
            log_http_error(e, "Auto-Lock Voice Channel", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
            ])
            return False, error_msg

        except Exception as e:
            error_msg = f"🔊{channel.name}: {str(e)[:LOG_TRUNCATE_SHORT]}"
            logger.error("Auto-Lock Channel Error", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                ("Type", type(e).__name__),
            ])
            return False, error_msg

    async def _unlock_text_channel(
        self,
        channel: discord.TextChannel,
        everyone_role: discord.Role,
        mod_role: Optional[discord.Role],
        saved_perms: Optional[Dict[str, Any]],
        reason: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Unlock a single text channel.

        Args:
            channel: The text channel to unlock.
            everyone_role: The @everyone role.
            mod_role: The moderation role (or None).
            saved_perms: Saved original permissions (or None).
            reason: Audit log reason.

        Returns:
            Tuple of (success, error_message).
        """
        try:
            current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

            if saved_perms:
                original_send = saved_perms.get("original_send_messages")
                current_overwrite.send_messages = original_send
                current_overwrite.add_reactions = original_send
                current_overwrite.create_public_threads = original_send
                current_overwrite.create_private_threads = original_send
                current_overwrite.send_messages_in_threads = original_send
            else:
                current_overwrite.send_messages = None
                current_overwrite.add_reactions = None
                current_overwrite.create_public_threads = None
                current_overwrite.create_private_threads = None
                current_overwrite.send_messages_in_threads = None

            if current_overwrite.is_empty():
                await channel.set_permissions(everyone_role, overwrite=None, reason=reason)
            else:
                await channel.set_permissions(everyone_role, overwrite=current_overwrite, reason=reason)

            # Remove mod role overwrites we added during lockdown
            if mod_role:
                mod_overwrite: discord.PermissionOverwrite = channel.overwrites_for(mod_role)
                # Set back to neutral (removes our explicit allows)
                mod_overwrite.send_messages = None
                mod_overwrite.add_reactions = None
                if mod_overwrite.is_empty():
                    await channel.set_permissions(mod_role, overwrite=None, reason=reason)
                else:
                    await channel.set_permissions(mod_role, overwrite=mod_overwrite, reason=reason)

            logger.debug("Auto-Unlock Channel", [
                ("Channel", f"#{channel.name}"),
                ("ID", str(channel.id)),
            ])

            return True, None

        except discord.Forbidden:
            logger.warning("Auto-Unlock Channel Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", "Forbidden"),
            ])
            return False, f"#{channel.name}: Missing permissions"

        except discord.HTTPException as e:
            log_http_error(e, "Auto-Unlock Text Channel", [
                ("Channel", f"#{channel.name} ({channel.id})"),
            ])
            return False, f"#{channel.name}: HTTP error"

        except Exception as e:
            logger.error("Auto-Unlock Channel Error", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                ("Type", type(e).__name__),
            ])
            return False, f"#{channel.name}: {str(e)[:LOG_TRUNCATE_SHORT]}"

    async def _unlock_voice_channel(
        self,
        channel: discord.VoiceChannel,
        everyone_role: discord.Role,
        mod_role: Optional[discord.Role],
        saved_perms: Optional[Dict[str, Any]],
        reason: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Unlock a single voice channel.

        Args:
            channel: The voice channel to unlock.
            everyone_role: The @everyone role.
            mod_role: The moderation role (or None).
            saved_perms: Saved original permissions (or None).
            reason: Audit log reason.

        Returns:
            Tuple of (success, error_message).
        """
        try:
            current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

            if saved_perms:
                original_connect = saved_perms.get("original_connect")
                current_overwrite.connect = original_connect
                current_overwrite.speak = original_connect
            else:
                current_overwrite.connect = None
                current_overwrite.speak = None

            if current_overwrite.is_empty():
                await channel.set_permissions(everyone_role, overwrite=None, reason=reason)
            else:
                await channel.set_permissions(everyone_role, overwrite=current_overwrite, reason=reason)

            # Remove mod role overwrites we added during lockdown
            if mod_role:
                mod_overwrite: discord.PermissionOverwrite = channel.overwrites_for(mod_role)
                mod_overwrite.connect = None
                mod_overwrite.speak = None
                if mod_overwrite.is_empty():
                    await channel.set_permissions(mod_role, overwrite=None, reason=reason)
                else:
                    await channel.set_permissions(mod_role, overwrite=mod_overwrite, reason=reason)

            logger.debug("Auto-Unlock Channel", [
                ("Channel", f"🔊{channel.name}"),
                ("ID", str(channel.id)),
            ])

            return True, None

        except discord.Forbidden:
            logger.warning("Auto-Unlock Channel Failed", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", "Forbidden"),
            ])
            return False, f"🔊{channel.name}: Missing permissions"

        except discord.HTTPException as e:
            log_http_error(e, "Auto-Unlock Voice Channel", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
            ])
            return False, f"🔊{channel.name}: HTTP error"

        except Exception as e:
            logger.error("Auto-Unlock Channel Error", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                ("Type", type(e).__name__),
            ])
            return False, f"🔊{channel.name}: {str(e)[:LOG_TRUNCATE_SHORT]}"

    async def _lock_all_channels(
        self,
        guild: discord.Guild,
        everyone_role: discord.Role,
        mod_role: Optional[discord.Role],
        reason: str,
    ) -> LockdownResult:
        """
        Lock all channels in a guild concurrently.

        Args:
            guild: The guild to lock.
            everyone_role: The @everyone role.
            mod_role: The moderation role (or None) - mods keep access.
            reason: Audit log reason.

        Returns:
            LockdownResult with counts and errors.
        """
        result = LockdownResult()
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_OPS)

        async def lock_with_semaphore(coro) -> Tuple[bool, Optional[str]]:
            async with semaphore:
                return await coro

        tasks: List[asyncio.Task] = []

        for channel in guild.text_channels:
            task = create_safe_task(
                lock_with_semaphore(self._lock_text_channel(channel, everyone_role, mod_role, reason)),
                f"Lock #{channel.name}",
            )
            tasks.append(task)

        for channel in guild.voice_channels:
            task = create_safe_task(
                lock_with_semaphore(self._lock_voice_channel(channel, everyone_role, mod_role, reason)),
                f"Lock 🔊{channel.name}",
            )
            tasks.append(task)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, Exception):
                    result.failed_count += 1
                    result.errors.append(str(res)[:100])
                    logger.error("Auto-Lock Task Exception", [
                        ("Error", str(res)[:100]),
                        ("Type", type(res).__name__),
                    ])
                elif isinstance(res, tuple):
                    success, error = res
                    if success:
                        result.success_count += 1
                    else:
                        result.failed_count += 1
                        if error:
                            result.errors.append(error)

        return result

    async def _unlock_all_channels(
        self,
        guild: discord.Guild,
        everyone_role: discord.Role,
        mod_role: Optional[discord.Role],
        reason: str,
    ) -> LockdownResult:
        """
        Unlock all channels in a guild concurrently.

        Args:
            guild: The guild to unlock.
            everyone_role: The @everyone role.
            mod_role: The moderation role (or None) - clean up mod overwrites.
            reason: Audit log reason.

        Returns:
            LockdownResult with counts and errors.
        """
        result = LockdownResult()
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_OPS)

        # Get saved channel permissions
        saved_channel_perms = self.db.get_channel_permissions(guild.id)
        saved_lookup: Dict[int, Dict[str, Any]] = {p["channel_id"]: p for p in saved_channel_perms}

        async def unlock_with_semaphore(coro) -> Tuple[bool, Optional[str]]:
            async with semaphore:
                return await coro

        tasks: List[asyncio.Task] = []

        for channel in guild.text_channels:
            saved = saved_lookup.get(channel.id)
            task = create_safe_task(
                unlock_with_semaphore(self._unlock_text_channel(channel, everyone_role, mod_role, saved, reason)),
                f"Unlock #{channel.name}",
            )
            tasks.append(task)

        for channel in guild.voice_channels:
            saved = saved_lookup.get(channel.id)
            task = create_safe_task(
                unlock_with_semaphore(self._unlock_voice_channel(channel, everyone_role, mod_role, saved, reason)),
                f"Unlock 🔊{channel.name}",
            )
            tasks.append(task)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, Exception):
                    result.failed_count += 1
                    result.errors.append(str(res)[:100])
                    logger.error("Auto-Unlock Task Exception", [
                        ("Error", str(res)[:100]),
                        ("Type", type(res).__name__),
                    ])
                elif isinstance(res, tuple):
                    success, error = res
                    if success:
                        result.success_count += 1
                    else:
                        result.failed_count += 1
                        if error:
                            result.errors.append(error)

        return result

    # =========================================================================
    # Main Lockdown Methods
    # =========================================================================

    async def trigger_raid_lockdown(
        self,
        guild: discord.Guild,
        join_count: int,
        time_window: int,
    ) -> bool:
        """
        Trigger automatic lockdown due to raid.

        Args:
            guild: The guild being raided.
            join_count: Number of joins detected.
            time_window: Time window in seconds.

        Returns:
            True if lockdown was triggered successfully.
        """
        # Check cooldown
        if self._last_auto_lockdown:
            elapsed: float = (datetime.now(NY_TZ) - self._last_auto_lockdown).total_seconds()
            if elapsed < LOCKDOWN_COOLDOWN:
                remaining: int = int(LOCKDOWN_COOLDOWN - elapsed)
                logger.debug("Raid Lockdown On Cooldown", [
                    ("Guild", f"{guild.name} ({guild.id})"),
                    ("Remaining", f"{remaining}s"),
                ])
                return False

        # Check if already locked
        if self.db.is_locked(guild.id):
            logger.debug("Raid Lockdown Skipped - Already Locked", [
                ("Guild", f"{guild.name} ({guild.id})"),
            ])
            return False

        # Get mod role so they keep access during lockdown
        mod_role: Optional[discord.Role] = None
        if self.config.moderation_role_id:
            mod_role = guild.get_role(self.config.moderation_role_id)

        logger.tree("RAID AUTO-LOCKDOWN INITIATED", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("Trigger", f"{join_count} joins in {time_window}s"),
            ("Text Channels", str(len(guild.text_channels))),
            ("Voice Channels", str(len(guild.voice_channels))),
            ("Mod Role", f"{mod_role.name} ({mod_role.id})" if mod_role else "None"),
        ], emoji="🚨")

        everyone_role: discord.Role = guild.default_role
        audit_reason: str = f"AUTO-LOCKDOWN: Raid detected ({join_count} joins in {time_window}s)"

        try:
            # Lock all channels concurrently (mods keep access)
            result: LockdownResult = await self._lock_all_channels(guild, everyone_role, mod_role, audit_reason)

            # Save lockdown state
            bot_id: int = self.bot.user.id if self.bot.user else 0
            self.db.start_lockdown(
                guild_id=guild.id,
                locked_by=bot_id,
                reason=f"Raid detected: {join_count} joins in {time_window}s",
                channel_count=result.success_count,
            )

            # Update cooldown
            self._last_auto_lockdown = datetime.now(NY_TZ)

            logger.tree("RAID AUTO-LOCKDOWN TRIGGERED", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Reason", f"{join_count} joins in {time_window}s"),
                ("Channels Locked", str(result.success_count)),
                ("Failed", str(result.failed_count)),
                ("Auto-Unlock", f"In {AUTO_UNLOCK_DURATION}s"),
            ], emoji="🚨")

            # Log to server logs
            if self.bot.logging_service and self.bot.logging_service.enabled:
                try:
                    await self.bot.logging_service.log_auto_lockdown(
                        join_count=join_count,
                        time_window=time_window,
                        auto_unlock_in=AUTO_UNLOCK_DURATION,
                    )
                except Exception as e:
                    logger.warning("Auto-Lockdown Server Log Failed", [
                        ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                    ])

            # Send public announcement
            await self._send_lockdown_announcement(guild, join_count, time_window)

            # Alert mods
            await self._alert_mods(guild, join_count, time_window)

            # Schedule auto-unlock
            if self._auto_unlock_task and not self._auto_unlock_task.done():
                self._auto_unlock_task.cancel()
                logger.debug("Previous Auto-Unlock Task Cancelled")

            self._auto_unlock_task = create_safe_task(
                self._auto_unlock(guild), "Raid Auto-Unlock"
            )

            return True

        except Exception as e:
            logger.error("Raid Auto-Lockdown Failed", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                ("Type", type(e).__name__),
            ])
            self.db.clear_lockdown_permissions(guild.id)
            return False

    async def _auto_unlock(self, guild: discord.Guild) -> None:
        """
        Auto-unlock server after duration.

        Args:
            guild: The guild to unlock.
        """
        try:
            logger.debug("Auto-Unlock Scheduled", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Duration", f"{AUTO_UNLOCK_DURATION}s"),
            ])

            await asyncio.sleep(AUTO_UNLOCK_DURATION)

            # Verify still locked
            if not self.db.is_locked(guild.id):
                logger.debug("Auto-Unlock Skipped - Not Locked", [
                    ("Guild", f"{guild.name} ({guild.id})"),
                ])
                return

            # Get mod role to clean up mod overwrites we added during lockdown
            mod_role: Optional[discord.Role] = None
            if self.config.moderation_role_id:
                mod_role = guild.get_role(self.config.moderation_role_id)

            logger.tree("AUTO-UNLOCK INITIATED", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Mod Role", f"{mod_role.name} ({mod_role.id})" if mod_role else "None"),
            ], emoji="🔓")

            everyone_role: discord.Role = guild.default_role
            audit_reason: str = "AUTO-UNLOCK: Raid lockdown expired"

            # Unlock all channels (clean up mod overwrites too)
            result: LockdownResult = await self._unlock_all_channels(guild, everyone_role, mod_role, audit_reason)

            # Clear lockdown state
            self.db.end_lockdown(guild.id)

            logger.tree("AUTO-UNLOCK COMPLETE", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Channels Unlocked", str(result.success_count)),
                ("Failed", str(result.failed_count)),
                ("Duration", f"{AUTO_UNLOCK_DURATION}s"),
            ], emoji="🔓")

            # Send public announcement
            await self._send_unlock_announcement(guild)

            # Log to server logs
            if self.bot.logging_service and self.bot.logging_service.enabled:
                try:
                    await self.bot.logging_service.log_auto_unlock()
                except Exception as e:
                    logger.warning("Auto-Unlock Server Log Failed", [
                        ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                    ])

        except asyncio.CancelledError:
            logger.debug("Auto-Unlock Task Cancelled", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Reason", "Manual unlock or new lockdown"),
            ])

        except Exception as e:
            logger.error("Auto-Unlock Failed", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                ("Type", type(e).__name__),
            ])

    # =========================================================================
    # Announcement Methods
    # =========================================================================

    async def _send_lockdown_announcement(
        self,
        guild: discord.Guild,
        join_count: int,
        time_window: int,
    ) -> bool:
        """
        Send lockdown announcement to general channel.

        Args:
            guild: The guild.
            join_count: Number of joins that triggered lockdown.
            time_window: Time window in seconds.

        Returns:
            True if sent successfully.
        """
        if not self.config.general_channel_id:
            return False

        channel = guild.get_channel(self.config.general_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            logger.debug("General Channel Not Found", [
                ("Channel ID", str(self.config.general_channel_id)),
            ])
            return False

        try:
            embed = discord.Embed(
                title="🚨 AUTOMATIC LOCKDOWN",
                description=(
                    "**A raid has been detected.**\n"
                    "The server has been automatically locked to protect members.\n\n"
                    f"Detected: `{join_count}` accounts joined in `{time_window}` seconds"
                ),
                color=EmbedColors.GOLD,
                timestamp=datetime.now(NY_TZ),
            )

            unlock_timestamp: int = int(datetime.now(NY_TZ).timestamp()) + AUTO_UNLOCK_DURATION
            embed.add_field(
                name="Auto-Unlock",
                value=f"<t:{unlock_timestamp}:R>",
                inline=True,
            )
            embed.add_field(
                name="Manual Unlock",
                value="Moderators can use `/unlock`",
                inline=True,
            )
            set_footer(embed)

            await channel.send(embed=embed)

            logger.debug("Lockdown Announcement Sent", [
                ("Channel", f"#{channel.name}"),
                ("Guild", f"{guild.name}"),
            ])

            return True

        except discord.Forbidden:
            logger.warning("Lockdown Announcement Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", "Forbidden - missing permissions"),
            ])
            return False

        except discord.HTTPException as e:
            log_http_error(e, "Lockdown Announcement", [
                ("Channel", f"#{channel.name} ({channel.id})"),
            ])
            return False

    async def _send_unlock_announcement(self, guild: discord.Guild) -> bool:
        """
        Send unlock announcement to general channel.

        Args:
            guild: The guild.

        Returns:
            True if sent successfully.
        """
        if not self.config.general_channel_id:
            return False

        channel = guild.get_channel(self.config.general_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return False

        try:
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

            await channel.send(embed=embed)

            logger.debug("Unlock Announcement Sent", [
                ("Channel", f"#{channel.name}"),
                ("Guild", f"{guild.name}"),
            ])

            return True

        except discord.Forbidden:
            logger.warning("Unlock Announcement Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", "Forbidden"),
            ])
            return False

        except discord.HTTPException as e:
            log_http_error(e, "Unlock Announcement", [
                ("Channel", f"#{channel.name} ({channel.id})"),
            ])
            return False

    async def _alert_mods(
        self,
        guild: discord.Guild,
        join_count: int,
        time_window: int,
    ) -> bool:
        """
        Alert mods in alert channel about the raid.

        Args:
            guild: The guild.
            join_count: Number of joins that triggered lockdown.
            time_window: Time window in seconds.

        Returns:
            True if sent successfully.
        """
        if not self.config.alert_channel_id:
            return False

        try:
            alert_channel = self.bot.get_channel(self.config.alert_channel_id)
            if not alert_channel or not isinstance(alert_channel, discord.TextChannel):
                logger.debug("Alert Channel Not Found", [
                    ("Channel ID", str(self.config.alert_channel_id)),
                ])
                return False

            embed = discord.Embed(
                title="🚨 RAID AUTO-LOCKDOWN TRIGGERED",
                description=f"Server **{guild.name}** has been automatically locked.",
                color=0xFF0000,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Detected", value=f"`{join_count}` joins in `{time_window}s`", inline=True)
            embed.add_field(name="Auto-Unlock", value=f"In `{AUTO_UNLOCK_DURATION}s`", inline=True)
            set_footer(embed)

            instructions: str = (
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

            logger.debug("Mod Alert Sent", [
                ("Channel", f"#{alert_channel.name}"),
                ("Guild", f"{guild.name}"),
            ])

            return True

        except discord.Forbidden:
            logger.warning("Mod Alert Failed", [
                ("Error", "Forbidden - missing permissions"),
            ])
            return False

        except discord.HTTPException as e:
            log_http_error(e, "Mod Alert", [])
            return False

        except Exception as e:
            logger.error("Mod Alert Error", [
                ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                ("Type", type(e).__name__),
            ])
            return False

    # =========================================================================
    # Public Methods
    # =========================================================================

    def cancel_auto_unlock(self) -> None:
        """Cancel pending auto-unlock (called when manual unlock happens)."""
        if self._auto_unlock_task and not self._auto_unlock_task.done():
            self._auto_unlock_task.cancel()
            self._auto_unlock_task = None
            logger.debug("Auto-Unlock Cancelled", [
                ("Reason", "Manual unlock"),
            ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["RaidLockdownService"]
