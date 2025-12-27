"""
Azab Discord Bot - Forbid Command Cog
======================================

Restrict specific permissions for users without fully muting them.

Features:
    /forbid @user <restriction> [reason] - Add a restriction
    /unforbid @user <restriction> - Remove a restriction
    /forbidden @user - View user's active restrictions

Restrictions:
    - reactions: Can't add reactions
    - attachments: Can't send files
    - voice: Can't join voice channels
    - streaming: Can join VC but can't stream
    - embeds: Can't send embeds/link previews
    - threads: Can't create threads
    - external_emojis: Can't use external emojis
    - stickers: Can't use stickers

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

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
    """Cog for user permission restrictions."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("Forbid Cog Loaded", [
            ("Commands", "/forbid, /unforbid, /forbidden"),
            ("Restrictions", str(len(RESTRICTIONS))),
        ], emoji="🚫")

    # =========================================================================
    # Role Management
    # =========================================================================

    def _get_role_name(self, restriction: str) -> str:
        """Get the role name for a restriction type."""
        display = RESTRICTIONS[restriction]["display"]
        return f"{FORBID_ROLE_PREFIX}{display}"

    async def _ensure_forbid_roles(self, guild: discord.Guild) -> dict:
        """
        Ensure all forbid roles exist in the guild.

        Returns dict mapping restriction type to role.
        """
        roles = {}

        for restriction, config in RESTRICTIONS.items():
            role_name = self._get_role_name(restriction)

            # Check if role exists
            role = discord.utils.get(guild.roles, name=role_name)

            if not role:
                # Create the role with denied permissions
                perms = discord.Permissions()

                # Handle single or multiple permissions
                if "permissions" in config:
                    for perm in config["permissions"]:
                        setattr(perms, perm, False)
                else:
                    setattr(perms, config["permission"], False)

                try:
                    role = await guild.create_role(
                        name=role_name,
                        permissions=perms,
                        color=discord.Color.dark_grey(),
                        reason="Forbid system: Creating restriction role",
                    )

                    # Move role to bottom (just above @everyone)
                    await role.edit(position=1)

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
        reason="Reason for the restriction",
    )
    @app_commands.autocomplete(restriction=restriction_autocomplete)
    @app_commands.default_permissions(moderate_members=True)
    async def forbid(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        restriction: str,
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

            # Can't forbid yourself
            if user.id == moderator.id:
                await interaction.followup.send(
                    "You cannot forbid yourself.",
                    ephemeral=True,
                )
                return

            # Can't forbid bots
            if user.bot:
                await interaction.followup.send(
                    "You cannot forbid bots.",
                    ephemeral=True,
                )
                return

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
                    self.db.add_forbid(user.id, guild.id, r, moderator.id, reason)
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
                ("Already Had", ", ".join(already_had) if already_had else "None"),
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
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Target", f"{user} ({user.id})"),
            ])
            try:
                await interaction.followup.send(
                    "An error occurred while applying restrictions.",
                    ephemeral=True,
                )
            except Exception:
                pass

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
            except Exception:
                pass

    # =========================================================================
    # Unforbid Command
    # =========================================================================

    @app_commands.command(name="unforbid", description="Remove a restriction from a user")
    @app_commands.describe(
        user="The user to unrestrict",
        restriction="What to unforbid (or 'all' to remove all)",
    )
    @app_commands.autocomplete(restriction=restriction_autocomplete)
    @app_commands.default_permissions(moderate_members=True)
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
            except Exception:
                pass

    # =========================================================================
    # Forbidden Command (View)
    # =========================================================================

    @app_commands.command(name="forbidden", description="View a user's active restrictions")
    @app_commands.describe(user="The user to check")
    @app_commands.default_permissions(moderate_members=True)
    async def forbidden(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        """View active restrictions for a user."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        try:
            forbids = self.db.get_user_forbids(user.id, interaction.guild.id)

            embed = discord.Embed(
                title=f"Restrictions for {user.display_name}",
                color=EmbedColors.GOLD if forbids else EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            embed.set_thumbnail(url=user.display_avatar.url)

            if forbids:
                for forbid in forbids:
                    r = forbid["restriction_type"]
                    if r in RESTRICTIONS:
                        config = RESTRICTIONS[r]
                        moderator = interaction.guild.get_member(forbid["moderator_id"])
                        mod_text = moderator.mention if moderator else f"<@{forbid['moderator_id']}>"

                        value = f"By: {mod_text}\n"
                        value += f"Since: <t:{int(forbid['created_at'])}:R>"
                        if forbid.get("reason"):
                            value += f"\nReason: {forbid['reason'][:100]}"

                        embed.add_field(
                            name=f"{config['emoji']} {config['display']}",
                            value=value,
                            inline=True,
                        )

                embed.description = f"**{len(forbids)}** active restriction(s)"
            else:
                embed.description = "No active restrictions"

            set_footer(embed)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error("Forbidden Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
            ])
            await interaction.response.send_message(
                "An error occurred.",
                ephemeral=True,
            )

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


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Forbid cog."""
    await bot.add_cog(ForbidCog(bot))
