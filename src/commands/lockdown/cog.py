"""
AzabBot - Lockdown Cog
======================

Emergency server lockdown commands.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.api.services.event_logger import event_logger
from src.core.database import get_db
from src.utils.discord_rate_limit import log_http_error

from .constants import MAX_CONCURRENT_OPS, LockdownResult
from .lock_ops import lock_all_channels
from .unlock_ops import unlock_all_channels
from .helpers import get_target_guild, send_public_announcement

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.core.config import Config
    from src.core.database.manager import DatabaseManager


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
    # Lockdown Command
    # =========================================================================

    @app_commands.command(name="lockdown", description="Lock the server instantly during an emergency")
    @app_commands.describe(reason="Reason for the lockdown")
    @app_commands.default_permissions(administrator=True)
    async def lockdown(
        self,
        interaction: discord.Interaction,
        reason: Optional[str] = None) -> None:
        """
        Lock server by setting channel permission overwrites.

        This command locks all text and voice channels by setting
        @everyone permission overwrites to deny send_messages/connect.
        Original permissions are saved and restored on unlock.
        """
        # Validate guild context
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True)
            return

        # Get target guild (cross-server support)
        guild: Optional[discord.Guild] = get_target_guild(interaction, self.bot)
        if not guild:
            logger.warning("Lockdown Target Not Found", [
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Source Guild", str(interaction.guild.id)),
            ])
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True)
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
                ephemeral=True)
            return

        # Defer response (this may take a while for large servers)
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass  # Interaction already responded or expired

        try:
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
            result: LockdownResult = await lock_all_channels(guild, everyone_role, mod_role, audit_reason, self.db)

            # Save lockdown state
            self.db.start_lockdown(
                guild_id=guild.id,
                locked_by=interaction.user.id,
                reason=reason,
                channel_count=result.success_count)

            # Build response embed
            embed = discord.Embed(
                title="🔒 Server Locked",
                description="**Server is now in lockdown mode.**\nMembers cannot send messages or join voice channels.",
                color=EmbedColors.ERROR
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
                inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

            # Log the action
            logger.tree("SERVER LOCKED", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Channels Locked", str(result.success_count)),
                ("Failed", str(result.failed_count)),
                ("Reason", reason or "None"),
            ], emoji="🔒")

            # Log to dashboard events
            if isinstance(interaction.user, discord.Member):
                event_logger.log_lockdown(
                    guild=guild,
                    moderator=interaction.user,
                    channel_count=result.success_count,
                    reason=reason)

            # Log to server logs service
            if self.bot.logging_service and self.bot.logging_service.enabled:
                try:
                    await self.bot.logging_service.log_lockdown(
                        moderator=interaction.user,
                        reason=reason,
                        channel_count=result.success_count,
                        action="lock")
                except Exception as e:
                    logger.warning("Server Log Failed", [
                        ("Error", str(e)[:100]),
                    ])

            # Send public announcement
            await send_public_announcement(guild, "lock", self.config)

        except discord.HTTPException as e:
            log_http_error(e, "Lockdown Command", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            try:
                await interaction.followup.send(
                    "An error occurred during lockdown.",
                    ephemeral=True)
            except discord.HTTPException:
                pass

        except Exception as e:
            logger.error("Lockdown Command Failed", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
            try:
                await interaction.followup.send(
                    "An unexpected error occurred.",
                    ephemeral=True)
            except discord.HTTPException:
                pass

    # =========================================================================
    # Unlock Command
    # =========================================================================

    @app_commands.command(name="unlock", description="Unlock the server after a lockdown")
    @app_commands.default_permissions(administrator=True)
    async def unlock(
        self,
        interaction: discord.Interaction) -> None:
        """
        Restore original channel permission overwrites.

        This command unlocks all text and voice channels by restoring
        the saved @everyone permission overwrites from before the lockdown.
        """
        # Validate guild context
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True)
            return

        # Get target guild (cross-server support)
        guild: Optional[discord.Guild] = get_target_guild(interaction, self.bot)
        if not guild:
            logger.warning("Unlock Target Not Found", [
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Source Guild", str(interaction.guild.id)),
            ])
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True)
            return

        # Check if locked
        if not self.db.is_locked(guild.id):
            logger.debug("Unlock - Not Locked", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user} ({interaction.user.id})"),
            ])
            await interaction.response.send_message(
                "Server is not currently locked.",
                ephemeral=True)
            return

        # Defer response
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass  # Interaction already responded or expired

        try:
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
            result: LockdownResult = await unlock_all_channels(guild, everyone_role, mod_role, audit_reason, self.db)

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
                color=EmbedColors.SUCCESS
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

            await interaction.followup.send(embed=embed, ephemeral=True)

            # Log the action
            logger.tree("SERVER UNLOCKED", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Channels Unlocked", str(result.success_count)),
                ("Failed", str(result.failed_count)),
                ("Duration", f"{int(duration_seconds)}s"),
            ], emoji="🔓")

            # Log to dashboard events
            if isinstance(interaction.user, discord.Member):
                event_logger.log_unlock(
                    guild=guild,
                    moderator=interaction.user,
                    channel_count=result.success_count)

            # Log to server logs service
            if self.bot.logging_service and self.bot.logging_service.enabled:
                try:
                    await self.bot.logging_service.log_lockdown(
                        moderator=interaction.user,
                        reason=None,
                        channel_count=result.success_count,
                        action="unlock")
                except Exception as e:
                    logger.warning("Server Log Failed", [
                        ("Error", str(e)[:100]),
                    ])

            # Send public announcement
            await send_public_announcement(guild, "unlock", self.config)

        except discord.HTTPException as e:
            log_http_error(e, "Unlock Command", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            try:
                await interaction.followup.send(
                    "An error occurred during unlock.",
                    ephemeral=True)
            except discord.HTTPException:
                pass

        except Exception as e:
            logger.error("Unlock Command Failed", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
            try:
                await interaction.followup.send(
                    "An unexpected error occurred.",
                    ephemeral=True)
            except discord.HTTPException:
                pass


__all__ = ["LockdownCog"]
