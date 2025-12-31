"""
Azab Discord Bot - Forbid Command Cog
======================================

Restrict specific permissions for users without fully muting them.

Features:
    /forbid @user <restriction> [duration] [reason] - Add a restriction
    /unforbid @user <restriction> - Remove a restriction

Restrictions:
    - reactions: Can't add reactions
    - attachments: Can't send files
    - voice: Can't join voice channels
    - streaming: Can join VC but can't stream
    - embeds: Can't send embeds/link previews
    - threads: Can't create threads
    - external_emojis: Can't use external emojis
    - stickers: Can't use stickers

Automation:
    - New channels automatically get forbid role overwrites
    - Nightly scan at 3 AM fixes any missing overwrites
    - Expiry scheduler checks every minute for expired forbids
    - DM notification sent to user when forbidden
    - Appeal integration for users to appeal restrictions

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ, is_developer, has_mod_role
from src.core.database import get_db
from src.core.moderation_validation import (
    validate_self_action,
    validate_target_not_bot,
    validate_role_hierarchy,
)
from src.utils.footer import set_footer
from src.utils.views import APPEAL_EMOJI
from src.utils.rate_limiter import rate_limit
from src.utils.duration import parse_duration, format_duration_short as format_duration

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Restriction types and their corresponding Discord permissions
RESTRICTIONS = {
    "reactions": {
        "permission": "add_reactions",
        "display": "Add Reactions",
        "emoji": "🚫",
        "description": "Cannot add reactions to messages",
    },
    "attachments": {
        "permission": "attach_files",
        "display": "Send Attachments",
        "emoji": "📎",
        "description": "Cannot send files or images",
    },
    "voice": {
        "permission": "connect",
        "display": "Join Voice",
        "emoji": "🔇",
        "description": "Cannot join voice channels",
    },
    "streaming": {
        "permission": "stream",
        "display": "Stream/Screenshare",
        "emoji": "📺",
        "description": "Cannot stream or screenshare in voice",
    },
    "embeds": {
        "permission": "embed_links",
        "display": "Embed Links",
        "emoji": "🔗",
        "description": "Cannot send embeds or link previews",
    },
    "threads": {
        "permissions": ["create_public_threads", "create_private_threads"],
        "display": "Create Threads",
        "emoji": "🧵",
        "description": "Cannot create threads",
    },
    "external_emojis": {
        "permission": "use_external_emojis",
        "display": "External Emojis",
        "emoji": "😀",
        "description": "Cannot use emojis from other servers",
    },
    "stickers": {
        "permission": "use_external_stickers",
        "display": "Stickers",
        "emoji": "🎨",
        "description": "Cannot use stickers",
    },
}

# Role name prefix for forbid roles
FORBID_ROLE_PREFIX = "Forbid: "


# =============================================================================
# Forbid Cog
# =============================================================================

class ForbidCog(commands.Cog):
    """Cog for user permission restrictions with duration, DM, and appeal support."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # Start background tasks
        self._scan_task = asyncio.create_task(self._start_nightly_scan())
        self._expiry_task = asyncio.create_task(self._start_expiry_scheduler())

        logger.tree("Forbid Cog Loaded", [
            ("Commands", "/forbid, /unforbid"),
            ("Restrictions", str(len(RESTRICTIONS))),
            ("Nightly Scan", "3 AM NY Time"),
        ], emoji="🚫")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use forbid commands."""
        return has_mod_role(interaction.user)

    # =========================================================================
    # Role Management
    # =========================================================================

    def _get_role_name(self, restriction: str) -> str:
        """Get the role name for a restriction type."""
        display = RESTRICTIONS[restriction]["display"]
        return f"{FORBID_ROLE_PREFIX}{display}"

    async def _ensure_forbid_roles(self, guild: discord.Guild) -> dict:
        """
        Ensure all forbid roles exist in the guild with proper channel overwrites.

        Returns dict mapping restriction type to role.
        """
        roles = {}

        for restriction, config in RESTRICTIONS.items():
            role_name = self._get_role_name(restriction)

            # Check if role exists
            role = discord.utils.get(guild.roles, name=role_name)

            if not role:
                try:
                    # Create the role (minimal permissions)
                    role = await guild.create_role(
                        name=role_name,
                        permissions=discord.Permissions.none(),
                        color=discord.Color.dark_grey(),
                        reason="Forbid system: Creating restriction role",
                    )

                    # Move role to bottom (just above @everyone)
                    await role.edit(position=1)

                    # Set channel overwrites to DENY the permission in all channels
                    await self._apply_channel_overwrites(guild, role, restriction)

                    logger.tree("Forbid Role Created", [
                        ("Role", role_name),
                        ("Guild", guild.name),
                    ], emoji="🔧")

                except discord.Forbidden:
                    logger.warning(f"Cannot create forbid role: {role_name}")
                    continue
                except discord.HTTPException as e:
                    logger.warning(f"Failed to create forbid role {role_name}: {e}")
                    continue

            roles[restriction] = role

        return roles

    async def _apply_channel_overwrites(
        self,
        guild: discord.Guild,
        role: discord.Role,
        restriction: str,
    ) -> None:
        """Apply permission overwrites to all channels for a forbid role."""
        config = RESTRICTIONS.get(restriction)
        if not config:
            return

        # Build the permission overwrite kwargs
        overwrite_kwargs = {}

        if "permissions" in config:
            for perm in config["permissions"]:
                overwrite_kwargs[perm] = False
        else:
            overwrite_kwargs[config["permission"]] = False

        overwrite = discord.PermissionOverwrite(**overwrite_kwargs)

        # Apply to all text channels (for embed_links, attach_files, etc.)
        text_perms = {"embed_links", "attach_files", "add_reactions",
                      "use_external_emojis", "use_external_stickers",
                      "create_public_threads", "create_private_threads"}

        # Apply to all voice channels (for connect, stream)
        voice_perms = {"connect", "stream"}

        # Determine which channel types need the overwrite
        perm_names = set(overwrite_kwargs.keys())
        apply_to_text = bool(perm_names & text_perms)
        apply_to_voice = bool(perm_names & voice_perms)

        for channel in guild.channels:
            try:
                if isinstance(channel, discord.TextChannel) and apply_to_text:
                    await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
                elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    # Voice channels need both voice AND text permissions (for VC text chat)
                    if apply_to_voice or apply_to_text:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
                elif isinstance(channel, discord.ForumChannel) and apply_to_text:
                    await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue

    async def _get_or_create_role(self, guild: discord.Guild, restriction: str) -> Optional[discord.Role]:
        """Get or create a specific forbid role."""
        role_name = self._get_role_name(restriction)
        role = discord.utils.get(guild.roles, name=role_name)

        if not role:
            roles = await self._ensure_forbid_roles(guild)
            role = roles.get(restriction)

        return role

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

    # =========================================================================
    # Forbid Command
    # =========================================================================

    @app_commands.command(name="forbid", description="Restrict a specific permission for a user")
    @app_commands.describe(
        user="The user to restrict",
        restriction="What to forbid (reactions, attachments, voice, streaming, embeds, threads, external_emojis, stickers, all)",
        duration="Duration (e.g., 7d, 24h, 1w) - leave empty for permanent",
        reason="Reason for the restriction",
    )
    @app_commands.autocomplete(restriction=restriction_autocomplete)
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

            # Validation using centralized module
            result = validate_self_action(moderator, user, "forbid")
            if not result.is_valid:
                await interaction.followup.send(result.error_message, ephemeral=True)
                return

            result = validate_target_not_bot(moderator, user, "forbid")
            if not result.is_valid:
                await interaction.followup.send(result.error_message, ephemeral=True)
                return

            # Hierarchy check
            if isinstance(moderator, discord.Member):
                result = validate_role_hierarchy(
                    moderator=moderator,
                    target=user,
                    target_guild=guild,
                    action="forbid",
                    cross_server=False,
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
                ("Moderator", f"{moderator} ({moderator.id})"),
                ("Target", f"{user} ({user.id})"),
                ("Restrictions", ", ".join(applied) if applied else "None new"),
                ("Duration", duration_display),
                ("Reason", (reason or "None")[:50]),
            ], emoji="🚫")

            # Build embed response
            embed = discord.Embed(
                title="🚫 User Restricted",
                color=EmbedColors.WARNING,
                timestamp=datetime.now(NY_TZ),
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)
            embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)
            embed.add_field(name="Duration", value=duration_display, inline=True)

            if applied:
                applied_text = "\n".join([f"{RESTRICTIONS[r]['emoji']} {r}" for r in applied])
                embed.add_field(name="Applied", value=applied_text, inline=False)

            if already_had:
                already_text = "\n".join([f"⚪ {r} (already active)" for r in already_had])
                embed.add_field(name="Already Had", value=already_text, inline=False)

            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            set_footer(embed)

            await interaction.followup.send(embed=embed, ephemeral=True)

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

            # Create case log
            if applied and self.bot.case_log_service:
                try:
                    await self.bot.case_log_service.log_forbid(
                        user=user,
                        moderator=moderator,
                        restrictions=applied,
                        reason=reason,
                        duration=duration_display,
                    )
                except Exception as e:
                    logger.debug(f"Failed to create forbid case: {e}")

        except discord.HTTPException as e:
            logger.error("Forbid Command Failed (HTTP)", [
                ("Error", str(e)),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Target", f"{user} ({user.id})"),
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
                ("User", f"{interaction.user} ({interaction.user.id})"),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "An error occurred.",
                        ephemeral=True,
                    )
            except Exception as e:
                logger.debug(f"Error response failed: {e}")

    # =========================================================================
    # Unforbid Command
    # =========================================================================

    @app_commands.command(name="unforbid", description="Remove a restriction from a user")
    @app_commands.describe(
        user="The user to unrestrict",
        restriction="What to unforbid (or 'all' to remove all)",
    )
    @app_commands.autocomplete(restriction=restriction_autocomplete)
    async def unforbid(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        restriction: str,
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
                ("Moderator", f"{moderator} ({moderator.id})"),
                ("Target", f"{user} ({user.id})"),
                ("Removed", ", ".join(removed)),
            ], emoji="✅")

            # DM user about restriction removal
            await self._send_unforbid_dm(user, removed, guild)

            # Build embed response
            embed = discord.Embed(
                title="✅ Restrictions Removed",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)
            embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)

            removed_text = "\n".join([f"{RESTRICTIONS[r]['emoji']} {r}" for r in removed])
            embed.add_field(name="Removed", value=removed_text, inline=False)

            set_footer(embed)

            await interaction.followup.send(embed=embed, ephemeral=True)

            # Log to server logs
            await self._log_forbid(
                interaction=interaction,
                user=user,
                restrictions=removed,
                reason=None,
                action="unforbid",
            )

            # Create case log
            if removed and self.bot.case_log_service:
                try:
                    await self.bot.case_log_service.log_unforbid(
                        user=user,
                        moderator=moderator,
                        restrictions=removed,
                    )
                except Exception as e:
                    logger.debug(f"Failed to create unforbid case: {e}")

        except Exception as e:
            logger.error("Unforbid Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
                ("User", f"{interaction.user} ({interaction.user.id})"),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "An error occurred.",
                        ephemeral=True,
                    )
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
                          "create_public_threads", "create_private_threads"}
            voice_perms = {"connect", "stream"}
            perm_names = set(overwrite_kwargs.keys())

            try:
                if isinstance(channel, (discord.TextChannel, discord.ForumChannel)) and (perm_names & text_perms):
                    await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system: new channel")
                elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    # Voice channels need both voice AND text permissions (for VC text chat)
                    if perm_names & voice_perms or perm_names & text_perms:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system: new channel")
            except (discord.Forbidden, discord.HTTPException):
                pass

    # =========================================================================
    # Nightly Scan Task
    # =========================================================================

    async def _start_nightly_scan(self) -> None:
        """Start the nightly scan loop."""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                # Calculate time until 3 AM NY time
                now = datetime.now(NY_TZ)
                target = now.replace(hour=3, minute=0, second=0, microsecond=0)

                # If it's past 3 AM today, schedule for tomorrow
                if now >= target:
                    target = target + timedelta(days=1)

                seconds_until = (target - now).total_seconds()

                # Wait until 3 AM
                await asyncio.sleep(seconds_until)

                # Run the scan
                await self._run_forbid_scan()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Forbid nightly scan error: {e}")
                # Wait an hour before retrying on error
                await asyncio.sleep(3600)

    async def _run_forbid_scan(self) -> None:
        """Scan all guilds and ensure forbid roles have correct overwrites."""
        logger.tree("Forbid Nightly Scan Started", [], emoji="🔍")

        total_fixed = 0

        for guild in self.bot.guilds:
            try:
                fixed = await self._scan_guild_forbids(guild)
                total_fixed += fixed
            except Exception as e:
                logger.debug(f"Forbid scan error for {guild.name}: {e}")

        logger.tree("Forbid Nightly Scan Complete", [
            ("Guilds Scanned", str(len(self.bot.guilds))),
            ("Overwrites Fixed", str(total_fixed)),
        ], emoji="✅")

    async def _scan_guild_forbids(self, guild: discord.Guild) -> int:
        """Scan a single guild for missing forbid overwrites. Returns count of fixes."""
        fixed = 0

        for restriction, config in RESTRICTIONS.items():
            role_name = self._get_role_name(restriction)
            role = discord.utils.get(guild.roles, name=role_name)

            if not role:
                continue

            # Build expected overwrite
            overwrite_kwargs = {}
            if "permissions" in config:
                for perm in config["permissions"]:
                    overwrite_kwargs[perm] = False
            else:
                overwrite_kwargs[config["permission"]] = False

            expected_overwrite = discord.PermissionOverwrite(**overwrite_kwargs)

            # Check text/voice channels based on permission type
            text_perms = {"embed_links", "attach_files", "add_reactions",
                          "use_external_emojis", "use_external_stickers",
                          "create_public_threads", "create_private_threads"}
            voice_perms = {"connect", "stream"}
            perm_names = set(overwrite_kwargs.keys())

            for channel in guild.channels:
                try:
                    needs_fix = False

                    # Check if this channel type needs the overwrite
                    if isinstance(channel, (discord.TextChannel, discord.ForumChannel)) and (perm_names & text_perms):
                        current = channel.overwrites_for(role)
                        for perm_name in overwrite_kwargs:
                            if getattr(current, perm_name) is not False:
                                needs_fix = True
                                break
                    elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                        # Voice channels need both voice AND text permissions (for VC text chat)
                        if perm_names & voice_perms or perm_names & text_perms:
                            current = channel.overwrites_for(role)
                            for perm_name in overwrite_kwargs:
                                if getattr(current, perm_name) is not False:
                                    needs_fix = True
                                    break

                    if needs_fix:
                        await channel.set_permissions(role, overwrite=expected_overwrite, reason="Forbid system: nightly scan fix")
                        fixed += 1
                        # Rate limit for permission changes
                        await rate_limit("role_modify")

                except (discord.Forbidden, discord.HTTPException):
                    continue

        return fixed

    # =========================================================================
    # Expiry Scheduler
    # =========================================================================

    async def _start_expiry_scheduler(self) -> None:
        """Start the expiry scheduler loop - checks every minute for expired forbids."""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                await self._process_expired_forbids()
                # Check every 60 seconds
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Forbid expiry scheduler error: {e}")
                await asyncio.sleep(60)

    async def _process_expired_forbids(self) -> None:
        """Process all expired forbids and remove them."""
        expired = self.db.get_expired_forbids()

        if not expired:
            return

        for forbid in expired:
            try:
                guild_id = forbid["guild_id"]
                user_id = forbid["user_id"]
                restriction_type = forbid["restriction_type"]

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    # Guild not accessible, just mark as removed in DB
                    self.db.remove_forbid(user_id, guild_id, restriction_type, self.bot.user.id)
                    continue

                member = guild.get_member(user_id)
                if not member:
                    # Member not in guild, just mark as removed in DB
                    self.db.remove_forbid(user_id, guild_id, restriction_type, self.bot.user.id)
                    continue

                # Get the forbid role
                role_name = self._get_role_name(restriction_type)
                role = discord.utils.get(guild.roles, name=role_name)

                if role and role in member.roles:
                    await member.remove_roles(role, reason="Forbid expired")

                # Mark as removed in DB
                self.db.remove_forbid(user_id, guild_id, restriction_type, self.bot.user.id)

                logger.tree("FORBID EXPIRED", [
                    ("User", f"{member} ({member.id})"),
                    ("Restriction", restriction_type),
                    ("Guild", guild.name),
                ], emoji="⏰")

                # DM user about expiry
                try:
                    expiry_embed = discord.Embed(
                        title="Restriction Expired",
                        description=f"Your **{RESTRICTIONS[restriction_type]['display']}** restriction has expired.",
                        color=EmbedColors.SUCCESS,
                        timestamp=datetime.now(NY_TZ),
                    )
                    expiry_embed.add_field(name="Server", value=guild.name, inline=True)
                    expiry_embed.add_field(name="Restriction", value=RESTRICTIONS[restriction_type]['display'], inline=True)
                    set_footer(expiry_embed)
                    await member.send(embed=expiry_embed)
                except (discord.Forbidden, discord.HTTPException):
                    pass

            except Exception as e:
                logger.debug(f"Error processing expired forbid: {e}")

    # =========================================================================
    # DM Notification
    # =========================================================================

    async def _send_forbid_dm(
        self,
        user: discord.Member,
        restrictions: List[str],
        duration_display: str,
        reason: Optional[str],
        guild: discord.Guild,
    ) -> bool:
        """Send DM notification to user when forbidden. Returns True if sent successfully."""
        try:
            # Build restrictions list
            restrictions_text = "\n".join([
                f"{RESTRICTIONS[r]['emoji']} **{RESTRICTIONS[r]['display']}** - {RESTRICTIONS[r]['description']}"
                for r in restrictions if r in RESTRICTIONS
            ])

            embed = discord.Embed(
                title="🚫 You've Been Restricted",
                description=f"A moderator has applied restrictions to your account in **{guild.name}**.",
                color=0xFF6B6B,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Restrictions Applied",
                value=restrictions_text,
                inline=False,
            )

            embed.add_field(name="Duration", value=duration_display, inline=True)

            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            embed.add_field(
                name="What This Means",
                value="These restrictions limit specific features. You can still participate in the server otherwise.",
                inline=False,
            )

            # Add appeal information
            embed.add_field(
                name="Want to Appeal?",
                value="If you believe this was a mistake, you can appeal using the button below or by contacting a moderator.",
                inline=False,
            )

            embed.set_footer(text=f"Server: {guild.name}")

            # Create appeal button view
            view = ForbidAppealView(guild.id, user.id)

            await user.send(embed=embed, view=view)
            return True

        except discord.Forbidden:
            logger.debug(f"Cannot DM {user} - DMs disabled")
            return False
        except discord.HTTPException as e:
            logger.debug(f"Failed to DM {user}: {e}")
            return False

    async def _send_unforbid_dm(
        self,
        user: discord.Member,
        restrictions: List[str],
        guild: discord.Guild,
    ) -> bool:
        """Send DM notification to user when restrictions are removed. Returns True if sent successfully."""
        try:
            # Build restrictions list
            restrictions_text = "\n".join([
                f"{RESTRICTIONS[r]['emoji']} **{RESTRICTIONS[r]['display']}**"
                for r in restrictions if r in RESTRICTIONS
            ])

            embed = discord.Embed(
                title="Restrictions Removed",
                description=f"Your restrictions in **{guild.name}** have been lifted.",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Removed Restrictions",
                value=restrictions_text,
                inline=False,
            )

            embed.add_field(
                name="What This Means",
                value="You now have full access to these features again.",
                inline=False,
            )

            embed.set_footer(text=f"Server: {guild.name}")

            await user.send(embed=embed)
            logger.debug(f"Unforbid DM sent to {user}")
            return True

        except discord.Forbidden:
            logger.debug(f"Cannot DM {user} - DMs disabled")
            return False
        except discord.HTTPException as e:
            logger.debug(f"Failed to DM {user}: {e}")
            return False


# =============================================================================
# Appeal View
# =============================================================================

class ForbidAppealButton(discord.ui.DynamicItem[discord.ui.Button], template=r"forbid_appeal:(?P<guild_id>\d+):(?P<user_id>\d+)"):
    """Persistent appeal button for forbid DMs."""

    def __init__(self, guild_id: int, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Appeal Restriction",
                style=discord.ButtonStyle.secondary,
                emoji=APPEAL_EMOJI,
                custom_id=f"forbid_appeal:{guild_id}:{user_id}",
            )
        )
        self.guild_id = guild_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "ForbidAppealButton":
        guild_id = int(match.group("guild_id"))
        user_id = int(match.group("user_id"))
        return cls(guild_id, user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle appeal button click."""
        # Show appeal modal
        modal = ForbidAppealModal(self.guild_id)
        await interaction.response.send_modal(modal)


class ForbidAppealView(discord.ui.View):
    """View with appeal button for forbid DMs."""

    def __init__(self, guild_id: int, user_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(ForbidAppealButton(guild_id, user_id))


class ForbidAppealModal(discord.ui.Modal):
    """Modal for submitting a forbid appeal."""

    def __init__(self, guild_id: int) -> None:
        super().__init__(title="Appeal Restriction")
        self.guild_id = guild_id

        self.reason = discord.ui.TextInput(
            label="Why should this restriction be removed?",
            style=discord.TextStyle.paragraph,
            placeholder="Explain why you believe the restriction was unfair or provide context...",
            required=True,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle appeal submission."""
        from src.bot import AzabBot

        bot: AzabBot = interaction.client  # type: ignore
        config = get_config()

        # Send appeal to mod channel
        try:
            guild = bot.get_guild(self.guild_id)
            if not guild:
                await interaction.response.send_message(
                    "Unable to submit appeal - server not found.",
                    ephemeral=True,
                )
                return

            # Try to send to alert channel or mod logs
            alert_channel = None
            if config.alert_channel_id:
                alert_channel = bot.get_channel(config.alert_channel_id)

            if not alert_channel and bot.logging_service and bot.logging_service.enabled:
                # Try to use the logging service
                try:
                    embed = discord.Embed(
                        title="📝 Forbid Appeal Submitted",
                        color=EmbedColors.INFO,
                        timestamp=datetime.now(NY_TZ),
                    )
                    embed.add_field(
                        name="User",
                        value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                        inline=True,
                    )
                    embed.add_field(
                        name="Appeal Reason",
                        value=self.reason.value,
                        inline=False,
                    )
                    embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    set_footer(embed)

                    await bot.logging_service._send_log(
                        bot.logging_service.LogCategory.MOD_ACTIONS,
                        embed,
                    )

                    await interaction.response.send_message(
                        "Your appeal has been submitted! A moderator will review it soon.",
                        ephemeral=True,
                    )
                    return

                except Exception as e:
                    logger.debug(f"Appeal via logging service failed: {e}")

            if alert_channel:
                embed = discord.Embed(
                    title="📝 Forbid Appeal Submitted",
                    color=EmbedColors.INFO,
                    timestamp=datetime.now(NY_TZ),
                )
                embed.add_field(
                    name="User",
                    value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                    inline=True,
                )
                embed.add_field(
                    name="Appeal Reason",
                    value=self.reason.value,
                    inline=False,
                )
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                set_footer(embed)

                await alert_channel.send(embed=embed)

            await interaction.response.send_message(
                "Your appeal has been submitted! A moderator will review it soon.",
                ephemeral=True,
            )

        except Exception as e:
            logger.debug(f"Failed to submit forbid appeal: {e}")
            await interaction.response.send_message(
                "Failed to submit appeal. Please contact a moderator directly.",
                ephemeral=True,
            )


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Forbid cog."""
    bot.add_dynamic_items(ForbidAppealButton)
    await bot.add_cog(ForbidCog(bot))
