"""
AzabBot - Cog
=============

Main ForbidCog class inheriting from all mixins.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ, has_mod_role
from src.core.database import get_db
from src.core.moderation_validation import validate_moderation_target
from src.utils.footer import set_footer
from src.views import CaseButtonView
from src.utils.duration import parse_duration, format_duration_short as format_duration
from src.utils.async_utils import create_safe_task
from src.core.constants import CASE_LOG_TIMEOUT, MODERATION_REASONS, MODERATION_REMOVAL_REASONS

# Import from local package
from .constants import RESTRICTIONS, FORBID_ROLE_PREFIX
from .roles import RolesMixin
from .scheduler import SchedulerMixin
from .dm import DMMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class ForbidCog(RolesMixin, SchedulerMixin, DMMixin, commands.Cog):
    """Cog for user permission restrictions with duration, DM, and appeal support."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # Guild roles cache: {guild_id: (roles_dict, cached_at)}
        self._roles_cache: Dict[int, Tuple[Dict[str, discord.Role], datetime]] = {}

        # Start background tasks (using create_safe_task for error logging)
        self._scan_task = create_safe_task(self._start_nightly_scan(), "Forbid Nightly Scan")
        self._expiry_task = create_safe_task(self._start_expiry_scheduler(), "Forbid Expiry Scheduler")
        self._startup_scan_task = create_safe_task(self._run_startup_scan(), "Forbid Startup Scan")

        logger.tree("Forbid Cog Loaded", [
            ("Commands", "/forbid, /unforbid"),
            ("Restrictions", str(len(RESTRICTIONS))),
            ("Startup Scan", "30s after ready"),
            ("Nightly Scan", "12:00 AM EST"),
        ], emoji="🚫")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use forbid commands."""
        return has_mod_role(interaction.user)

    # =========================================================================
    # Autocomplete
    # =========================================================================

    async def restriction_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for restriction types."""
        choices = []

        # Add "all" option
        if "all".startswith(current.lower()):
            choices.append(app_commands.Choice(name="all - All restrictions", value="all"))

        for key, config in RESTRICTIONS.items():
            if current.lower() in key.lower() or current.lower() in config["display"].lower():
                choices.append(app_commands.Choice(
                    name=f"{config['emoji']} {key} - {config['description']}",
                    value=key,
                ))

        return choices[:25]

    async def reason_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for reason parameter."""
        choices = []
        current_lower = current.lower()

        for reason in MODERATION_REASONS:
            if current_lower in reason.lower():
                choices.append(app_commands.Choice(name=reason, value=reason))

        # Include custom input if provided
        if current and current not in MODERATION_REASONS:
            choices.insert(0, app_commands.Choice(name=current, value=current))

        return choices[:25]

    async def removal_reason_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for removal reason parameter (unforbid)."""
        choices = []
        current_lower = current.lower()

        for reason in MODERATION_REMOVAL_REASONS:
            if current_lower in reason.lower():
                choices.append(app_commands.Choice(name=reason, value=reason))

        # Include custom input if provided
        if current and current not in MODERATION_REMOVAL_REASONS:
            choices.insert(0, app_commands.Choice(name=current, value=current))

        return choices[:25]

    # =========================================================================
    # Forbid Command
    # =========================================================================

    @app_commands.command(name="forbid", description="Restrict a specific permission for a user")
    @app_commands.describe(
        user="The user to restrict",
        restriction="What to forbid (reactions, embeds, attachments, voice_messages, polls, external_emojis, stickers, threads, voice, streaming, all)",
        duration="Duration (e.g., 7d, 24h, 1w) - leave empty for permanent",
        reason="Reason for the restriction",
    )
    @app_commands.autocomplete(restriction=restriction_autocomplete, reason=reason_autocomplete)
    async def forbid(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        restriction: str,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Forbid a user from using a specific feature."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)

            guild = interaction.guild
            moderator = interaction.user

            # Validate restriction
            restriction = restriction.lower()
            if restriction != "all" and restriction not in RESTRICTIONS:
                await interaction.followup.send(
                    f"Invalid restriction. Choose from: `{', '.join(RESTRICTIONS.keys())}` or `all`",
                    ephemeral=True,
                )
                return

            # Validation using centralized module (self, bot, hierarchy, management)
            result = await validate_moderation_target(
                interaction=interaction,
                target=user,
                bot=self.bot,
                action="forbid",
                require_member=True,
                check_bot_hierarchy=False,  # Forbid uses roles, not direct Discord actions
            )
            if not result.is_valid:
                await interaction.followup.send(result.error_message, ephemeral=True)
                return

            # Parse duration
            duration_seconds = None
            expires_at = None
            duration_display = "Permanent"

            if duration:
                duration_seconds = parse_duration(duration)
                if duration_seconds is None:
                    await interaction.followup.send(
                        "Invalid duration format. Use: `7d`, `24h`, `1w`, `30m`, etc.",
                        ephemeral=True,
                    )
                    return
                expires_at = datetime.now(NY_TZ).timestamp() + duration_seconds
                duration_display = format_duration(duration_seconds)

            # Determine which restrictions to apply
            if restriction == "all":
                restrictions_to_apply = list(RESTRICTIONS.keys())
            else:
                restrictions_to_apply = [restriction]

            applied = []
            already_had = []
            failed = []

            for r in restrictions_to_apply:
                # Check if already forbidden
                if self.db.is_forbidden(user.id, guild.id, r):
                    already_had.append(r)
                    continue

                # Get or create role
                role = await self._get_or_create_role(guild, r)
                if not role:
                    failed.append(r)
                    continue

                try:
                    await user.add_roles(role, reason=f"Forbid by {moderator}: {reason or 'No reason'}")
                    self.db.add_forbid(user.id, guild.id, r, moderator.id, reason, expires_at)
                    applied.append(r)
                except discord.Forbidden:
                    failed.append(r)
                except discord.HTTPException:
                    failed.append(r)

            # Build response
            if not applied and not already_had:
                await interaction.followup.send(
                    "Failed to apply any restrictions. Check bot permissions.",
                    ephemeral=True,
                )
                return

            # Tree logging
            logger.tree("USER FORBIDDEN", [
                ("Moderator", f"{moderator.name} ({moderator.nick})" if hasattr(moderator, 'nick') and moderator.nick else moderator.name),
                ("Mod ID", str(moderator.id)),
                ("Target", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("Target ID", str(user.id)),
                ("Restrictions", ", ".join(applied) if applied else "None new"),
                ("Duration", duration_display),
                ("Reason", (reason or "None")[:50]),
            ], emoji="🚫")

            # Create case log FIRST (need case_info for public embed)
            case_info = None
            if applied and self.bot.case_log_service:
                try:
                    case_info = await asyncio.wait_for(
                        self.bot.case_log_service.log_forbid(
                            user=user,
                            moderator=moderator,
                            restrictions=applied,
                            reason=reason,
                            duration=duration_display,
                        ),
                        timeout=CASE_LOG_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Case Log Timeout", [
                        ("Action", "Forbid"),
                        ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                        ("ID", str(user.id)),
                    ])
                except Exception as e:
                    logger.error("Case Log Failed", [
                        ("Action", "Forbid"),
                        ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                        ("ID", str(user.id)),
                        ("Error", str(e)[:100]),
                    ])

            # Build embed response
            embed = discord.Embed(
                title="🚫 User Restricted",
                color=EmbedColors.WARNING,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)
            embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)
            embed.add_field(name="Duration", value=duration_display, inline=True)

            if case_info:
                embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)

            if applied:
                applied_text = "\n".join([f"{RESTRICTIONS[r]['emoji']} {r}" for r in applied])
                embed.add_field(name="Applied", value=applied_text, inline=False)

            if already_had:
                already_text = "\n".join([f"⚪ {r} (already active)" for r in already_had])
                embed.add_field(name="Already Had", value=already_text, inline=False)

            # Note: Reason intentionally not shown in public embed
            embed.set_thumbnail(url=user.display_avatar.url)
            set_footer(embed)

            # Send public embed with buttons
            if case_info:
                view = CaseButtonView(guild.id, case_info["thread_id"], user.id)
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed)

            # Send DM notification to user
            if applied:
                dm_sent = await self._send_forbid_dm(
                    user=user,
                    restrictions=applied,
                    duration_display=duration_display,
                    reason=reason,
                    guild=guild,
                )
                if dm_sent:
                    logger.debug(f"Forbid DM sent to {user}")

            # Log to server logs
            await self._log_forbid(
                interaction=interaction,
                user=user,
                restrictions=applied,
                reason=reason,
                action="forbid",
            )

        except discord.HTTPException as e:
            logger.error("Forbid Command Failed (HTTP)", [
                ("Error", str(e)),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
                ("Target", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("Target ID", str(user.id)),
            ])
            try:
                await interaction.followup.send(
                    "An error occurred while applying restrictions.",
                    ephemeral=True,
                )
            except Exception as e:
                logger.debug(f"Error response failed: {e}")

        except Exception as e:
            logger.error("Forbid Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
            ])
            try:
                response_done = False
                try:
                    response_done = interaction.response.is_done()
                except discord.HTTPException:
                    response_done = True  # Assume done if we can't check

                if not response_done:
                    await interaction.response.send_message(
                        "An error occurred.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "An error occurred.",
                        ephemeral=True,
                    )
            except discord.HTTPException:
                pass
            except Exception as e:
                logger.debug(f"Error response failed: {e}")

    # =========================================================================
    # Unforbid Command
    # =========================================================================

    @app_commands.command(name="unforbid", description="Remove a restriction from a user")
    @app_commands.describe(
        user="The user to unrestrict",
        restriction="What to unforbid (or 'all' to remove all)",
        reason="Reason for removing the restriction",
    )
    @app_commands.autocomplete(restriction=restriction_autocomplete, reason=removal_reason_autocomplete)
    async def unforbid(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        restriction: str,
        reason: Optional[str] = None,
    ) -> None:
        """Remove a restriction from a user."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)

            guild = interaction.guild
            moderator = interaction.user

            # Validate restriction
            restriction = restriction.lower()
            if restriction != "all" and restriction not in RESTRICTIONS:
                await interaction.followup.send(
                    f"Invalid restriction. Choose from: `{', '.join(RESTRICTIONS.keys())}` or `all`",
                    ephemeral=True,
                )
                return

            # Determine which restrictions to remove
            if restriction == "all":
                restrictions_to_remove = list(RESTRICTIONS.keys())
            else:
                restrictions_to_remove = [restriction]

            removed = []
            not_had = []
            failed = []

            for r in restrictions_to_remove:
                # Check if forbidden
                if not self.db.is_forbidden(user.id, guild.id, r):
                    not_had.append(r)
                    continue

                # Get role
                role_name = self._get_role_name(r)
                role = discord.utils.get(guild.roles, name=role_name)

                if role and role in user.roles:
                    try:
                        await user.remove_roles(role, reason=f"Unforbid by {moderator}")
                        self.db.remove_forbid(user.id, guild.id, r, moderator.id)
                        removed.append(r)
                    except discord.Forbidden:
                        failed.append(r)
                    except discord.HTTPException:
                        failed.append(r)
                else:
                    # Role doesn't exist or user doesn't have it, just update DB
                    self.db.remove_forbid(user.id, guild.id, r, moderator.id)
                    removed.append(r)

            # Build response
            if not removed:
                await interaction.followup.send(
                    f"{user.mention} doesn't have any of those restrictions.",
                    ephemeral=True,
                )
                return

            # Tree logging
            logger.tree("USER UNFORBIDDEN", [
                ("Moderator", f"{moderator.name} ({moderator.nick})" if hasattr(moderator, 'nick') and moderator.nick else moderator.name),
                ("Mod ID", str(moderator.id)),
                ("Target", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("Target ID", str(user.id)),
                ("Removed", ", ".join(removed)),
                ("Reason", reason or "No reason provided"),
            ], emoji="✅")

            # Create case log FIRST (need case_info for public embed)
            case_info = None
            if removed and self.bot.case_log_service:
                try:
                    case_info = await asyncio.wait_for(
                        self.bot.case_log_service.log_unforbid(
                            user=user,
                            moderator=moderator,
                            restrictions=removed,
                            reason=reason,
                        ),
                        timeout=CASE_LOG_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Case Log Timeout", [
                        ("Action", "Unforbid"),
                        ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                        ("ID", str(user.id)),
                    ])
                except Exception as e:
                    logger.error("Case Log Failed", [
                        ("Action", "Unforbid"),
                        ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                        ("ID", str(user.id)),
                        ("Error", str(e)[:100]),
                    ])

            # DM user about restriction removal
            await self._send_unforbid_dm(user, removed, guild)

            # Build embed response
            embed = discord.Embed(
                title="✅ Restrictions Removed",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)
            embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)

            if case_info:
                embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)

            removed_text = "\n".join([f"{RESTRICTIONS[r]['emoji']} {r}" for r in removed])
            embed.add_field(name="Removed", value=removed_text, inline=False)

            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            embed.set_thumbnail(url=user.display_avatar.url)
            set_footer(embed)

            # Send public embed with buttons
            if case_info:
                view = CaseButtonView(guild.id, case_info["thread_id"], user.id)
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed)

            # Log to server logs
            await self._log_forbid(
                interaction=interaction,
                user=user,
                restrictions=removed,
                reason=None,
                action="unforbid",
            )

        except Exception as e:
            logger.error("Unforbid Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
            ])
            try:
                response_done = False
                try:
                    response_done = interaction.response.is_done()
                except discord.HTTPException:
                    response_done = True  # Assume done if we can't check

                if not response_done:
                    await interaction.response.send_message(
                        "An error occurred.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "An error occurred.",
                        ephemeral=True,
                    )
            except discord.HTTPException:
                pass
            except Exception as e:
                logger.debug(f"Error response failed: {e}")

    # =========================================================================
    # Server Logs Integration
    # =========================================================================

    async def _log_forbid(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        restrictions: List[str],
        reason: Optional[str],
        action: str,
    ) -> None:
        """Log forbid/unforbid to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        if not restrictions:
            return

        try:
            if action == "forbid":
                title = "🚫 User Restricted"
                color = EmbedColors.WARNING
            else:
                title = "✅ Restrictions Removed"
                color = EmbedColors.SUCCESS

            embed = discord.Embed(
                title=title,
                color=color,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Moderator",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True,
            )
            embed.add_field(
                name="Target",
                value=f"{user.mention}\n`{user.id}`",
                inline=True,
            )
            embed.add_field(
                name="Channel",
                value=f"{interaction.channel.mention}" if interaction.channel else "Unknown",
                inline=True,
            )

            restrictions_text = "\n".join([
                f"{RESTRICTIONS[r]['emoji']} {RESTRICTIONS[r]['display']}"
                for r in restrictions if r in RESTRICTIONS
            ])
            embed.add_field(
                name="Restrictions",
                value=restrictions_text or "None",
                inline=False,
            )

            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed,
            )

        except Exception as e:
            logger.debug(f"Failed to log forbid action: {e}")

    # =========================================================================
    # Channel Creation Listener
    # =========================================================================

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Apply forbid role overwrites to newly created channels."""
        if not channel.guild:
            return

        guild = channel.guild
        applied_roles = []
        failed_roles = []

        # Find all existing forbid roles and apply their overwrites
        for restriction, config in RESTRICTIONS.items():
            role_name = self._get_role_name(restriction)
            role = discord.utils.get(guild.roles, name=role_name)

            if not role:
                continue

            # Build the permission overwrite
            overwrite_kwargs = {}
            if "permissions" in config:
                for perm in config["permissions"]:
                    overwrite_kwargs[perm] = False
            else:
                overwrite_kwargs[config["permission"]] = False

            overwrite = discord.PermissionOverwrite(**overwrite_kwargs)

            # Determine if this channel type needs the overwrite
            text_perms = {"embed_links", "attach_files", "add_reactions",
                          "use_external_emojis", "use_external_stickers",
                          "create_public_threads", "create_private_threads",
                          "send_voice_messages", "send_polls"}
            voice_perms = {"connect", "stream"}
            perm_names = set(overwrite_kwargs.keys())

            try:
                # Apply to new categories (children inherit these permissions)
                if isinstance(channel, discord.CategoryChannel):
                    if perm_names & text_perms or perm_names & voice_perms:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system: new category")
                        applied_roles.append(restriction)
                elif isinstance(channel, (discord.TextChannel, discord.ForumChannel)) and (perm_names & text_perms):
                    await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system: new channel")
                    applied_roles.append(restriction)
                elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    # Voice channels need both voice AND text permissions (for VC text chat)
                    if perm_names & voice_perms or perm_names & text_perms:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system: new channel")
                        applied_roles.append(restriction)
            except (discord.Forbidden, discord.HTTPException):
                failed_roles.append(restriction)

        if applied_roles:
            logger.tree("Forbid Overwrites Applied to New Channel", [
                ("Channel", f"#{channel.name}"),
                ("Type", type(channel).__name__),
                ("Guild", guild.name),
                ("Roles Applied", ", ".join(applied_roles)),
            ], emoji="🔒")

        if failed_roles:
            logger.warning("Forbid Overwrites Failed on New Channel", [
                ("Channel", f"#{channel.name}"),
                ("Guild", guild.name),
                ("Failed Roles", ", ".join(failed_roles)),
            ])


__all__ = ["ForbidCog"]
