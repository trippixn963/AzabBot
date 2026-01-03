"""
Azab Discord Bot - Lockdown Command Cog
========================================

Emergency server lockdown command for raid protection.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Lockdown Cog
# =============================================================================

class LockdownCog(commands.Cog):
    """Cog for emergency server lockdown commands."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("Lockdown Cog Loaded", [
            ("Commands", "/lockdown, /unlock"),
            ("Method", "Role-based (instant)"),
        ], emoji="🔒")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_target_guild(self, interaction: discord.Interaction) -> Optional[discord.Guild]:
        """
        Get the target guild for lockdown (supports cross-server moderation).

        If in mod server and main guild is configured, target main guild.
        """
        if (self.config.mod_server_id and
            self.config.logging_guild_id and
            interaction.guild and
            interaction.guild.id == self.config.mod_server_id):
            main_guild = self.bot.get_guild(self.config.logging_guild_id)
            if main_guild:
                return main_guild
        return interaction.guild

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
        """Lock server by modifying @everyone role permissions."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Get target guild (cross-server support)
        guild = self._get_target_guild(interaction)
        if not guild:
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True,
            )
            return

        # Check if already locked
        if self.db.is_locked(guild.id):
            lockdown_state = self.db.get_lockdown_state(guild.id)
            locked_at = lockdown_state.get("locked_at", 0) if lockdown_state else 0
            await interaction.response.send_message(
                f"Server is already locked since <t:{int(locked_at)}:R>.\n"
                f"Use `/unlock` to restore permissions.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

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

            # Apply lockdown - single API call
            await everyone_role.edit(
                permissions=new_perms,
                reason=f"Lockdown by {interaction.user}: {reason or 'Emergency'}",
            )

            # Save lockdown state
            self.db.start_lockdown(
                guild_id=guild.id,
                locked_by=interaction.user.id,
                reason=reason,
                channel_count=len(guild.channels),
            )

            # Build response embed
            embed = discord.Embed(
                title="🔒 Server Locked",
                description="**Server is now in lockdown mode.**\nMembers cannot send messages or join voice channels.",
                color=EmbedColors.ERROR,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
            embed.add_field(name="Method", value="Instant (role-based)", inline=True)
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
                ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("Mod ID", str(interaction.user.id)),
                ("Method", "Role-based (instant)"),
                ("Reason", reason or "None"),
            ], emoji="🔒")

            # Log to server logs
            if self.bot.logging_service and self.bot.logging_service.enabled:
                await self.bot.logging_service.log_lockdown(
                    moderator=interaction.user,
                    reason=reason,
                    channel_count=len(guild.channels),
                    action="lock",
                )

            # Public announcement
            if self.config.general_channel_id:
                general_channel = guild.get_channel(self.config.general_channel_id)
                if general_channel and isinstance(general_channel, discord.TextChannel):
                    announcement = discord.Embed(
                        title="🔒 Server Locked",
                        description="This server is currently in **lockdown mode**.\nPlease stand by while moderators handle the situation.",
                        color=EmbedColors.ERROR,
                        timestamp=datetime.now(NY_TZ),
                    )
                    set_footer(announcement)
                    try:
                        await general_channel.send(embed=announcement)
                    except discord.HTTPException:
                        pass  # Silently fail if can't send

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to modify the @everyone role.",
                ephemeral=True,
            )
            # Clean up saved permissions
            self.db.clear_lockdown_permissions(guild.id)
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Failed to lock server: {e}",
                ephemeral=True,
            )
            self.db.clear_lockdown_permissions(guild.id)

    # =========================================================================
    # Unlock Command
    # =========================================================================

    @app_commands.command(name="unlock", description="Unlock the server after a lockdown")
    @app_commands.default_permissions(administrator=True)
    async def unlock(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Restore original @everyone role permissions."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Get target guild (cross-server support)
        guild = self._get_target_guild(interaction)
        if not guild:
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True,
            )
            return

        # Check if locked
        if not self.db.is_locked(guild.id):
            await interaction.response.send_message(
                "Server is not currently locked.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        everyone_role = guild.default_role

        # Get saved permissions
        saved_perms = self.db.get_lockdown_permissions(guild.id)
        if not saved_perms:
            # Fallback to default permissions if not saved
            saved_perms = {
                "send_messages": True,
                "connect": True,
                "add_reactions": True,
                "create_public_threads": True,
                "create_private_threads": True,
                "send_messages_in_threads": True,
            }

        # Get lockdown info for duration calculation
        lockdown_state = self.db.get_lockdown_state(guild.id)
        locked_at = lockdown_state.get("locked_at", 0) if lockdown_state else 0
        duration_seconds = datetime.now(NY_TZ).timestamp() - locked_at if locked_at else 0

        try:
            # Restore original permissions
            new_perms = discord.Permissions(everyone_role.permissions.value)
            new_perms.update(
                send_messages=saved_perms.get("send_messages", True),
                connect=saved_perms.get("connect", True),
                add_reactions=saved_perms.get("add_reactions", True),
                create_public_threads=saved_perms.get("create_public_threads", True),
                create_private_threads=saved_perms.get("create_private_threads", True),
                send_messages_in_threads=saved_perms.get("send_messages_in_threads", True),
            )

            # Apply unlock - single API call
            await everyone_role.edit(
                permissions=new_perms,
                reason=f"Lockdown ended by {interaction.user}",
            )

            # Clear lockdown state
            self.db.end_lockdown(guild.id)

            # Cancel any pending auto-unlock
            if self.bot.raid_lockdown_service:
                self.bot.raid_lockdown_service.cancel_auto_unlock()

            # Build response embed
            embed = discord.Embed(
                title="🔓 Server Unlocked",
                description="**Server lockdown has ended.**\nMembers can now send messages and join voice channels.",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)

            if duration_seconds > 0:
                minutes = int(duration_seconds // 60)
                seconds = int(duration_seconds % 60)
                if minutes > 0:
                    embed.add_field(name="Duration", value=f"`{minutes}m {seconds}s`", inline=True)
                else:
                    embed.add_field(name="Duration", value=f"`{seconds}s`", inline=True)

            set_footer(embed)

            await interaction.followup.send(embed=embed, ephemeral=True)

            # Log the action
            logger.tree("SERVER UNLOCKED", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("Mod ID", str(interaction.user.id)),
                ("Duration", f"{int(duration_seconds)}s"),
            ], emoji="🔓")

            # Log to server logs
            if self.bot.logging_service and self.bot.logging_service.enabled:
                await self.bot.logging_service.log_lockdown(
                    moderator=interaction.user,
                    reason=None,
                    channel_count=len(guild.channels),
                    action="unlock",
                )

            # Public announcement
            if self.config.general_channel_id:
                general_channel = guild.get_channel(self.config.general_channel_id)
                if general_channel and isinstance(general_channel, discord.TextChannel):
                    announcement = discord.Embed(
                        title="🔓 Server Unlocked",
                        description="The lockdown has been lifted.\nYou may now resume normal activity.",
                        color=EmbedColors.SUCCESS,
                        timestamp=datetime.now(NY_TZ),
                    )
                    set_footer(announcement)
                    try:
                        await general_channel.send(embed=announcement)
                    except discord.HTTPException:
                        pass  # Silently fail if can't send

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to modify the @everyone role.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Failed to unlock server: {e}",
                ephemeral=True,
            )


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Lockdown cog."""
    await bot.add_cog(LockdownCog(bot))
