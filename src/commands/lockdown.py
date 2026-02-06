"""
AzabBot - Lockdown Command Cog
==============================

Emergency server lockdown command for raid protection.

Features:
- Channel-by-channel permission overwrites (works with any server config)
- Concurrent channel locking for speed
- Saves and restores original permissions
- Cross-server moderation support
- Comprehensive logging and error handling

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Tuple, List

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.async_utils import create_safe_task

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.core.config import Config
    from src.core.database.manager import DatabaseManager


# =============================================================================
# Constants
# =============================================================================

# Maximum concurrent channel operations (Discord rate limit friendly)
MAX_CONCURRENT_OPS: int = 10

# Delay between batches to avoid rate limits (seconds)
BATCH_DELAY: float = 0.5


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class LockdownResult:
    """Result of a lockdown/unlock operation."""
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    errors: List[str] = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


# =============================================================================
# Lockdown Cog
# =============================================================================

class LockdownCog(commands.Cog):
    """Cog for emergency server lockdown commands."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot: "AzabBot" = bot
        self.config: "Config" = get_config()
        self.db: "DatabaseManager" = get_db()

        logger.tree("Lockdown Cog Loaded", [
            ("Commands", "/lockdown, /unlock"),
            ("Method", "Channel overwrites (concurrent)"),
            ("Max Concurrent", str(MAX_CONCURRENT_OPS)),
        ], emoji="🔒")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_target_guild(self, interaction: discord.Interaction) -> Optional[discord.Guild]:
        """
        Get the target guild for lockdown (supports cross-server moderation).

        If in mod server and main guild is configured, target main guild.

        Args:
            interaction: The Discord interaction.

        Returns:
            Target guild or None if not found.
        """
        if (self.config.mod_server_id and
            self.config.logging_guild_id and
            interaction.guild and
            interaction.guild.id == self.config.mod_server_id):
            main_guild = self.bot.get_guild(self.config.logging_guild_id)
            if main_guild:
                logger.debug("Cross-Server Lockdown", [
                    ("From", f"{interaction.guild.name} ({interaction.guild.id})"),
                    ("Target", f"{main_guild.name} ({main_guild.id})"),
                ])
                return main_guild
        return interaction.guild

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
            # Get current @everyone overwrite for this channel
            current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

            # Save original permission state
            self.db.save_channel_permission(
                guild_id=channel.guild.id,
                channel_id=channel.id,
                channel_type="text",
                send_messages=current_overwrite.send_messages,
                connect=None,
            )

            # Set overwrite to deny messaging permissions
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

            logger.debug("Channel Locked", [
                ("Channel", f"#{channel.name}"),
                ("ID", str(channel.id)),
                ("Type", "text"),
                ("Mod Access", "yes" if mod_role else "no"),
            ])

            return True, None

        except discord.Forbidden as e:
            error_msg = f"#{channel.name}: Missing permissions"
            logger.warning("Channel Lock Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", "Forbidden - missing permissions"),
            ])
            return False, error_msg

        except discord.HTTPException as e:
            error_msg = f"#{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
            logger.warning("Channel Lock Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
            ])
            return False, error_msg

        except Exception as e:
            error_msg = f"#{channel.name}: {str(e)[:50]}"
            logger.error("Channel Lock Error", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
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

            logger.debug("Channel Locked", [
                ("Channel", f"🔊{channel.name}"),
                ("ID", str(channel.id)),
                ("Type", "voice"),
                ("Mod Access", "yes" if mod_role else "no"),
            ])

            return True, None

        except discord.Forbidden:
            error_msg = f"🔊{channel.name}: Missing permissions"
            logger.warning("Channel Lock Failed", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", "Forbidden - missing permissions"),
            ])
            return False, error_msg

        except discord.HTTPException as e:
            error_msg = f"🔊{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
            logger.warning("Channel Lock Failed", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
            ])
            return False, error_msg

        except Exception as e:
            error_msg = f"🔊{channel.name}: {str(e)[:50]}"
            logger.error("Channel Lock Error", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            return False, error_msg

    async def _unlock_text_channel(
        self,
        channel: discord.TextChannel,
        everyone_role: discord.Role,
        mod_role: Optional[discord.Role],
        saved_perms: Optional[dict],
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
                # Restore original permission (None = not set, True/False = explicit)
                original_send = saved_perms.get("original_send_messages")
                current_overwrite.send_messages = original_send
                current_overwrite.add_reactions = original_send
                current_overwrite.create_public_threads = original_send
                current_overwrite.create_private_threads = original_send
                current_overwrite.send_messages_in_threads = original_send
            else:
                # No saved state - remove explicit denies (set to None/neutral)
                current_overwrite.send_messages = None
                current_overwrite.add_reactions = None
                current_overwrite.create_public_threads = None
                current_overwrite.create_private_threads = None
                current_overwrite.send_messages_in_threads = None

            # If overwrite is now empty, remove it entirely
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

            logger.debug("Channel Unlocked", [
                ("Channel", f"#{channel.name}"),
                ("ID", str(channel.id)),
                ("Restored", "saved" if saved_perms else "default"),
            ])

            return True, None

        except discord.Forbidden:
            error_msg = f"#{channel.name}: Missing permissions"
            logger.warning("Channel Unlock Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", "Forbidden"),
            ])
            return False, error_msg

        except discord.HTTPException as e:
            error_msg = f"#{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
            logger.warning("Channel Unlock Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
            ])
            return False, error_msg

        except Exception as e:
            error_msg = f"#{channel.name}: {str(e)[:50]}"
            logger.error("Channel Unlock Error", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            return False, error_msg

    async def _unlock_voice_channel(
        self,
        channel: discord.VoiceChannel,
        everyone_role: discord.Role,
        mod_role: Optional[discord.Role],
        saved_perms: Optional[dict],
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

            logger.debug("Channel Unlocked", [
                ("Channel", f"🔊{channel.name}"),
                ("ID", str(channel.id)),
                ("Restored", "saved" if saved_perms else "default"),
            ])

            return True, None

        except discord.Forbidden:
            error_msg = f"🔊{channel.name}: Missing permissions"
            logger.warning("Channel Unlock Failed", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", "Forbidden"),
            ])
            return False, error_msg

        except discord.HTTPException as e:
            error_msg = f"🔊{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
            logger.warning("Channel Unlock Failed", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
            ])
            return False, error_msg

        except Exception as e:
            error_msg = f"🔊{channel.name}: {str(e)[:50]}"
            logger.error("Channel Unlock Error", [
                ("Channel", f"🔊{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            return False, error_msg

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

        # Build list of lock tasks
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

        # Execute all tasks concurrently
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, Exception):
                    result.failed_count += 1
                    result.errors.append(str(res)[:100])
                    logger.error("Lock Task Exception", [
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
        saved_lookup = {p["channel_id"]: p for p in saved_channel_perms}

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
                    logger.error("Unlock Task Exception", [
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

    async def _send_public_announcement(
        self,
        guild: discord.Guild,
        action: str,
    ) -> bool:
        """
        Send public announcement to general channel.

        Args:
            guild: The guild.
            action: "lock" or "unlock".

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
            if action == "lock":
                embed = discord.Embed(
                    title="🔒 Server Locked",
                    description="This server is currently in **lockdown mode**.\nPlease stand by while moderators handle the situation.",
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
            else:
                embed = discord.Embed(
                    title="🔓 Server Unlocked",
                    description="The lockdown has been lifted.\nYou may now resume normal activity.",
                    color=EmbedColors.SUCCESS,
                    timestamp=datetime.now(NY_TZ),
                )

            set_footer(embed)
            await channel.send(embed=embed)

            logger.debug("Public Announcement Sent", [
                ("Channel", f"#{channel.name}"),
                ("Action", action),
            ])
            return True

        except discord.Forbidden:
            logger.warning("Announcement Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", "Missing permissions"),
            ])
            return False

        except discord.HTTPException as e:
            logger.warning("Announcement Failed", [
                ("Channel", f"#{channel.name} ({channel.id})"),
                ("Error", str(e)[:100]),
            ])
            return False

    # =========================================================================
    # Lockdown Command
    # =========================================================================

    @app_commands.command(name="lockdown", description="Lock the server instantly during an emergency")
    @app_commands.describe(reason="Reason for the lockdown")
    @app_commands.default_permissions(administrator=True)
    async def lockdown(
        self,
        interaction: discord.Interaction,
        reason: Optional[str] = None,
    ) -> None:
        """
        Lock server by setting channel permission overwrites.

        This command locks all text and voice channels by setting
        @everyone permission overwrites to deny send_messages/connect.
        Original permissions are saved and restored on unlock.

        Args:
            interaction: The Discord interaction.
            reason: Optional reason for the lockdown.
        """
        # Validate guild context
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Get target guild (cross-server support)
        guild: Optional[discord.Guild] = self._get_target_guild(interaction)
        if not guild:
            logger.warning("Lockdown Target Not Found", [
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Source Guild", str(interaction.guild.id)),
            ])
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True,
            )
            return

        # Check if already locked
        if self.db.is_locked(guild.id):
            lockdown_state = self.db.get_lockdown_state(guild.id)
            locked_at = lockdown_state.get("locked_at", 0) if lockdown_state else 0

            logger.debug("Lockdown Already Active", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Locked At", str(int(locked_at))),
            ])

            await interaction.response.send_message(
                f"Server is already locked since <t:{int(locked_at)}:R>.\n"
                f"Use `/unlock` to restore permissions.",
                ephemeral=True,
            )
            return

        # Defer response (this may take a while for large servers)
        await interaction.response.defer(ephemeral=True)

        # Get mod role so they keep access during lockdown
        mod_role: Optional[discord.Role] = None
        if self.config.moderation_role_id:
            mod_role = guild.get_role(self.config.moderation_role_id)

        logger.tree("LOCKDOWN INITIATED", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Text Channels", str(len(guild.text_channels))),
            ("Voice Channels", str(len(guild.voice_channels))),
            ("Mod Role", f"{mod_role.name} ({mod_role.id})" if mod_role else "None"),
            ("Reason", reason or "None"),
        ], emoji="🔒")

        everyone_role: discord.Role = guild.default_role
        audit_reason: str = f"Lockdown by {interaction.user}: {reason or 'Emergency'}"

        # Lock all channels concurrently (mods keep access)
        result: LockdownResult = await self._lock_all_channels(guild, everyone_role, mod_role, audit_reason)

        # Save lockdown state
        self.db.start_lockdown(
            guild_id=guild.id,
            locked_by=interaction.user.id,
            reason=reason,
            channel_count=result.success_count,
        )

        # Build response embed
        embed = discord.Embed(
            title="🔒 Server Locked",
            description="**Server is now in lockdown mode.**\nMembers cannot send messages or join voice channels.",
            color=EmbedColors.ERROR,
            timestamp=datetime.now(NY_TZ),
        )
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Channels Locked", value=f"`{result.success_count}`", inline=True)

        if result.failed_count > 0:
            embed.add_field(name="Failed", value=f"`{result.failed_count}`", inline=True)
            # Add first few errors if any
            if result.errors:
                error_preview = "\n".join(result.errors[:3])
                if len(result.errors) > 3:
                    error_preview += f"\n... and {len(result.errors) - 3} more"
                embed.add_field(name="Errors", value=f"```{error_preview}```", inline=False)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        embed.add_field(
            name="Restore",
            value="Use `/unlock` to restore permissions",
            inline=False,
        )
        set_footer(embed)

        await interaction.followup.send(embed=embed, ephemeral=True)

        # Log the action
        logger.tree("SERVER LOCKED", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channels Locked", str(result.success_count)),
            ("Failed", str(result.failed_count)),
            ("Reason", reason or "None"),
        ], emoji="🔒")

        # Log to server logs service
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                await self.bot.logging_service.log_lockdown(
                    moderator=interaction.user,
                    reason=reason,
                    channel_count=result.success_count,
                    action="lock",
                )
            except Exception as e:
                logger.warning("Server Log Failed", [
                    ("Error", str(e)[:100]),
                ])

        # Send public announcement
        await self._send_public_announcement(guild, "lock")

    # =========================================================================
    # Unlock Command
    # =========================================================================

    @app_commands.command(name="unlock", description="Unlock the server after a lockdown")
    @app_commands.default_permissions(administrator=True)
    async def unlock(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        Restore original channel permission overwrites.

        This command unlocks all text and voice channels by restoring
        the saved @everyone permission overwrites from before the lockdown.

        Args:
            interaction: The Discord interaction.
        """
        # Validate guild context
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Get target guild (cross-server support)
        guild: Optional[discord.Guild] = self._get_target_guild(interaction)
        if not guild:
            logger.warning("Unlock Target Not Found", [
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Source Guild", str(interaction.guild.id)),
            ])
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True,
            )
            return

        # Check if locked
        if not self.db.is_locked(guild.id):
            logger.debug("Unlock - Not Locked", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user} ({interaction.user.id})"),
            ])
            await interaction.response.send_message(
                "Server is not currently locked.",
                ephemeral=True,
            )
            return

        # Defer response
        await interaction.response.defer(ephemeral=True)

        # Get lockdown info for duration calculation
        lockdown_state = self.db.get_lockdown_state(guild.id)
        locked_at: float = lockdown_state.get("locked_at", 0) if lockdown_state else 0
        duration_seconds: float = datetime.now(NY_TZ).timestamp() - locked_at if locked_at else 0

        # Get mod role to clean up mod overwrites we added during lockdown
        mod_role: Optional[discord.Role] = None
        if self.config.moderation_role_id:
            mod_role = guild.get_role(self.config.moderation_role_id)

        logger.tree("UNLOCK INITIATED", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Locked Duration", f"{int(duration_seconds)}s"),
            ("Mod Role", f"{mod_role.name} ({mod_role.id})" if mod_role else "None"),
        ], emoji="🔓")

        everyone_role: discord.Role = guild.default_role
        audit_reason: str = f"Lockdown ended by {interaction.user}"

        # Unlock all channels concurrently (clean up mod overwrites too)
        result: LockdownResult = await self._unlock_all_channels(guild, everyone_role, mod_role, audit_reason)

        # Clear lockdown state
        self.db.end_lockdown(guild.id)

        # Cancel any pending auto-unlock
        if self.bot.raid_lockdown_service:
            self.bot.raid_lockdown_service.cancel_auto_unlock()
            logger.debug("Auto-Unlock Cancelled", [
                ("Reason", "Manual unlock"),
            ])

        # Build response embed
        embed = discord.Embed(
            title="🔓 Server Unlocked",
            description="**Server lockdown has ended.**\nMembers can now send messages and join voice channels.",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Channels Unlocked", value=f"`{result.success_count}`", inline=True)

        if result.failed_count > 0:
            embed.add_field(name="Failed", value=f"`{result.failed_count}`", inline=True)

        if duration_seconds > 0:
            minutes: int = int(duration_seconds // 60)
            seconds: int = int(duration_seconds % 60)
            duration_str: str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            embed.add_field(name="Duration", value=f"`{duration_str}`", inline=True)

        set_footer(embed)

        await interaction.followup.send(embed=embed, ephemeral=True)

        # Log the action
        logger.tree("SERVER UNLOCKED", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Channels Unlocked", str(result.success_count)),
            ("Failed", str(result.failed_count)),
            ("Duration", f"{int(duration_seconds)}s"),
        ], emoji="🔓")

        # Log to server logs service
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                await self.bot.logging_service.log_lockdown(
                    moderator=interaction.user,
                    reason=None,
                    channel_count=result.success_count,
                    action="unlock",
                )
            except Exception as e:
                logger.warning("Server Log Failed", [
                    ("Error", str(e)[:100]),
                ])

        # Send public announcement
        await self._send_public_announcement(guild, "unlock")


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Lockdown cog."""
    await bot.add_cog(LockdownCog(bot))
