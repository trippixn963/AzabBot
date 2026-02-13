"""
AzabBot - Roles Mixin
=====================

Role management and channel overwrites for forbid system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, Optional, Tuple

import discord

from src.core.logger import logger
from src.utils.discord_rate_limit import log_http_error

from .constants import RESTRICTIONS, FORBID_ROLE_PREFIX

if TYPE_CHECKING:
    from src.commands.forbid.cog import ForbidCog


class RolesMixin:
    """Mixin for forbid role management."""

    # Cache TTL for guild roles (5 minutes)
    ROLES_CACHE_TTL = timedelta(minutes=5)

    def _get_role_name(self: "ForbidCog", restriction: str) -> str:
        """Get the role name for a restriction type."""
        display = RESTRICTIONS[restriction]["display"]
        return f"{FORBID_ROLE_PREFIX}{display}"

    async def _ensure_forbid_roles(
        self: "ForbidCog",
        guild: discord.Guild
    ) -> dict:
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
                    logger.warning("Forbid Role Creation Forbidden", [
                        ("Role", role_name),
                        ("Guild", guild.name),
                        ("Reason", "Missing permissions"),
                    ])
                    continue
                except discord.HTTPException as e:
                    log_http_error(e, "Forbid Role Creation", [
                        ("Role", role_name),
                        ("Guild", guild.name),
                    ])
                    continue

            roles[restriction] = role

        return roles

    async def _apply_channel_overwrites(
        self: "ForbidCog",
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
                      "create_public_threads", "create_private_threads",
                      "send_voice_messages", "send_polls"}

        # Apply to all voice channels (for connect, stream)
        voice_perms = {"connect", "stream"}

        # Determine which channel types need the overwrite
        perm_names = set(overwrite_kwargs.keys())
        apply_to_text = bool(perm_names & text_perms)
        apply_to_voice = bool(perm_names & voice_perms)

        # Apply to ALL channels - Discord does NOT propagate category overwrites to existing children
        applied_count = 0
        failed_count = 0

        for channel in guild.channels:
            try:
                if isinstance(channel, discord.CategoryChannel):
                    if apply_to_text or apply_to_voice:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
                        applied_count += 1
                elif isinstance(channel, (discord.TextChannel, discord.ForumChannel)) and apply_to_text:
                    await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
                    applied_count += 1
                elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    # Voice channels need both voice AND text permissions (for VC text chat)
                    if apply_to_voice or apply_to_text:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
                        applied_count += 1
            except discord.Forbidden:
                failed_count += 1
                continue
            except discord.HTTPException:
                failed_count += 1
                continue

        if applied_count > 0 or failed_count > 0:
            logger.tree("Forbid Overwrites Applied", [
                ("Role", role.name),
                ("Guild", guild.name),
                ("Channels", str(applied_count)),
                ("Failed", str(failed_count)),
            ], emoji="🔒")

    async def _get_or_create_role(
        self: "ForbidCog",
        guild: discord.Guild,
        restriction: str
    ) -> Optional[discord.Role]:
        """Get or create a specific forbid role with caching."""
        now = datetime.now()

        # Check cache first
        if guild.id in self._roles_cache:
            cached_roles, cached_at = self._roles_cache[guild.id]
            if now - cached_at < self.ROLES_CACHE_TTL:
                role = cached_roles.get(restriction)
                if role:
                    # Verify role still exists in guild
                    if discord.utils.get(guild.roles, id=role.id):
                        return role
                    # Role was deleted, invalidate cache
                    self._roles_cache.pop(guild.id, None)

        # Try to find role by name
        role_name = self._get_role_name(restriction)
        role = discord.utils.get(guild.roles, name=role_name)

        if not role:
            # Create roles and cache them
            roles = await self._ensure_forbid_roles(guild)
            self._roles_cache[guild.id] = (roles, now)
            role = roles.get(restriction)
        else:
            # Role exists - ensure channel overwrites are applied
            # (handles case where new permissions were added to the restriction)
            await self._apply_channel_overwrites(guild, role, restriction)

            # Update cache with this role
            if guild.id in self._roles_cache:
                self._roles_cache[guild.id][0][restriction] = role
            else:
                self._roles_cache[guild.id] = ({restriction: role}, now)

        return role


__all__ = ["RolesMixin"]
