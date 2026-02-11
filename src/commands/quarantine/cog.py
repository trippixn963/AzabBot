"""
AzabBot - Quarantine Cog
========================

Commands for managing anti-nuke quarantine mode.

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
from src.core.config import get_config, EmbedColors, NY_TZ, is_owner
from src.api.services.event_logger import event_logger
from src.utils.discord_rate_limit import log_http_error

from .helpers import get_target_guild, log_quarantine_action

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.core.config import Config


class QuarantineCog(commands.Cog):
    """Cog for quarantine mode commands."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot: "AzabBot" = bot
        self.config: "Config" = get_config()

        logger.tree("Quarantine Cog Loaded", [
            ("Commands", "/quarantine, /unquarantine, /quarantine-status"),
            ("Purpose", "Emergency role permission lockdown"),
        ], emoji="🔒")

    # =========================================================================
    # Quarantine Command
    # =========================================================================

    @app_commands.command(name="quarantine", description="Activate quarantine mode - strips dangerous permissions from all roles")
    @app_commands.describe(reason="Reason for activating quarantine")
    @app_commands.default_permissions(administrator=True)
    async def quarantine(
        self,
        interaction: discord.Interaction,
        reason: Optional[str] = None,
    ) -> None:
        """
        Activate quarantine mode.

        This strips all dangerous permissions (admin, ban, kick, etc.)
        from all roles except the owner's top role and the bot's role.
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Only owner can activate quarantine
        if not is_owner(interaction.user.id):
            await interaction.response.send_message(
                "Only the bot owner can activate quarantine mode.",
                ephemeral=True,
            )
            return

        if not self.bot.antinuke_service:
            await interaction.response.send_message(
                "Anti-nuke service is not available.",
                ephemeral=True,
            )
            return

        guild = get_target_guild(interaction, self.bot)
        if not guild:
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True,
            )
            return

        # Check if already quarantined
        if self.bot.antinuke_service.is_quarantined(guild.id):
            await interaction.response.send_message(
                "Server is already in quarantine mode.\n"
                "Use `/unquarantine` to lift it.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        logger.tree("QUARANTINE COMMAND", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Reason", reason or "Manual activation"),
        ], emoji="🔒")

        try:
            success = await self.bot.antinuke_service.quarantine_guild(
                guild,
                reason=reason or "Manual activation via command",
            )

            if success:
                embed = discord.Embed(
                    title="🔒 Quarantine Activated",
                    description=(
                        "**Server is now in quarantine mode.**\n\n"
                        "All dangerous permissions have been stripped from roles.\n"
                        "Only the server owner and this bot retain full permissions.\n\n"
                        "Use `/unquarantine` to restore permissions when safe."
                    ),
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
                if reason:
                    embed.add_field(name="Reason", value=reason, inline=False)

                await interaction.followup.send(embed=embed, ephemeral=True)

                # Log to dashboard events
                if isinstance(interaction.user, discord.Member):
                    event_logger.log_quarantine(
                        guild=guild,
                        moderator=interaction.user,
                        reason=reason,
                    )

                # Log to server logs
                await log_quarantine_action(self.bot, interaction.user, guild, "activate", reason)
            else:
                logger.warning("Quarantine Activation Failed", [
                    ("Guild", f"{guild.name} ({guild.id})"),
                    ("User", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Result", "Service returned False"),
                ])
                await interaction.followup.send(
                    "Failed to activate quarantine mode. Check logs for details.",
                    ephemeral=True,
                )

        except discord.HTTPException as e:
            log_http_error(e, "Quarantine Command", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.followup.send(
                f"Failed to activate quarantine: {e.text[:100] if e.text else 'HTTP error'}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Quarantine Command Failed", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            await interaction.followup.send(
                "An unexpected error occurred. Check logs for details.",
                ephemeral=True,
            )

    # =========================================================================
    # Unquarantine Command
    # =========================================================================

    @app_commands.command(name="unquarantine", description="Lift quarantine mode and restore role permissions")
    @app_commands.default_permissions(administrator=True)
    async def unquarantine(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Lift quarantine mode and restore original role permissions."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        # Only owner can lift quarantine
        if not is_owner(interaction.user.id):
            await interaction.response.send_message(
                "Only the bot owner can lift quarantine mode.",
                ephemeral=True,
            )
            return

        if not self.bot.antinuke_service:
            await interaction.response.send_message(
                "Anti-nuke service is not available.",
                ephemeral=True,
            )
            return

        guild = get_target_guild(interaction, self.bot)
        if not guild:
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True,
            )
            return

        # Check if quarantined
        if not self.bot.antinuke_service.is_quarantined(guild.id):
            await interaction.response.send_message(
                "Server is not in quarantine mode.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        logger.tree("UNQUARANTINE COMMAND", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
        ], emoji="🔓")

        try:
            success = await self.bot.antinuke_service.lift_quarantine(guild)

            if success:
                embed = discord.Embed(
                    title="🔓 Quarantine Lifted",
                    description=(
                        "**Quarantine mode has been deactivated.**\n\n"
                        "All role permissions have been restored to their "
                        "original state before the lockdown."
                    ),
                    color=EmbedColors.SUCCESS,
                    timestamp=datetime.now(NY_TZ),
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

                # Log to dashboard events
                if isinstance(interaction.user, discord.Member):
                    event_logger.log_unquarantine(
                        guild=guild,
                        moderator=interaction.user,
                    )

                # Log to server logs
                await log_quarantine_action(self.bot, interaction.user, guild, "lift", None)
            else:
                logger.warning("Quarantine Lift Failed", [
                    ("Guild", f"{guild.name} ({guild.id})"),
                    ("User", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Result", "Service returned False"),
                ])
                await interaction.followup.send(
                    "Failed to lift quarantine mode. Check logs for details.",
                    ephemeral=True,
                )

        except discord.HTTPException as e:
            log_http_error(e, "Unquarantine Command", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.followup.send(
                f"Failed to lift quarantine: {e.text[:100] if e.text else 'HTTP error'}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Unquarantine Command Failed", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            await interaction.followup.send(
                "An unexpected error occurred. Check logs for details.",
                ephemeral=True,
            )

    # =========================================================================
    # Quarantine Status Command
    # =========================================================================

    @app_commands.command(name="quarantine-status", description="Check if server is in quarantine mode")
    @app_commands.default_permissions(administrator=True)
    async def quarantine_status(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Check quarantine status."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not self.bot.antinuke_service:
            await interaction.response.send_message(
                "Anti-nuke service is not available.",
                ephemeral=True,
            )
            return

        guild = get_target_guild(interaction, self.bot)
        if not guild:
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True,
            )
            return

        try:
            is_quarantined = self.bot.antinuke_service.is_quarantined(guild.id)

            logger.debug("Quarantine Status Check", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Status", "Active" if is_quarantined else "Inactive"),
            ])

            if is_quarantined:
                roles_affected = len(self.bot.antinuke_service._quarantine_backup.get(guild.id, {}))
                embed = discord.Embed(
                    title="🔒 Quarantine Status: ACTIVE",
                    description=(
                        f"**{guild.name}** is currently in quarantine mode.\n\n"
                        f"Roles with stripped permissions: **{roles_affected}**\n\n"
                        f"Use `/unquarantine` to restore permissions."
                    ),
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
            else:
                embed = discord.Embed(
                    title="🔓 Quarantine Status: Inactive",
                    description=f"**{guild.name}** is not in quarantine mode.",
                    color=EmbedColors.SUCCESS,
                    timestamp=datetime.now(NY_TZ),
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except discord.HTTPException as e:
            log_http_error(e, "Quarantine Status", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.response.send_message(
                "Failed to check quarantine status.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Quarantine Status Failed", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            await interaction.response.send_message(
                "An unexpected error occurred.",
                ephemeral=True,
            )


__all__ = ["QuarantineCog"]
