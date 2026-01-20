"""
Forbid Command - Roles Mixin
============================

Role management and channel overwrites for forbid system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, Optional, Tuple

import discord

from src.core.logger import logger

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
                    logger.warning("Forbid Role Creation Failed", [
                        ("Role", role_name),
                        ("Guild", guild.name),
                        ("Error", str(e)[:100]),
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
                      "create_public_threads", "create_private_threads"}

        # Apply to all voice channels (for connect, stream)
        voice_perms = {"connect", "stream"}

        # Determine which channel types need the overwrite
        perm_names = set(overwrite_kwargs.keys())
        apply_to_text = bool(perm_names & text_perms)
        apply_to_voice = bool(perm_names & voice_perms)

        # OPTIMIZATION: Only apply to categories (children inherit) and uncategorized channels
        # This reduces API calls from O(all_channels) to O(categories + orphan_channels)
        categorized_channels = set()
        for category in guild.categories:
            categorized_channels.update(c.id for c in category.channels)

        for channel in guild.channels:
            try:
                # Always apply to categories (children inherit these permissions)
                if isinstance(channel, discord.CategoryChannel):
                    if apply_to_text or apply_to_voice:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
                # Only apply to uncategorized channels (orphans don't inherit from categories)
                elif channel.id not in categorized_channels:
                    if isinstance(channel, discord.TextChannel) and apply_to_text:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
                    elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                        if apply_to_voice or apply_to_text:
                            await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
                    elif isinstance(channel, discord.ForumChannel) and apply_to_text:
                        await channel.set_permissions(role, overwrite=overwrite, reason="Forbid system")
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue

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
                    try:
                        del self._roles_cache[guild.id]
                    except KeyError:
                        pass  # Already removed by another coroutine

        # Try to find role by name
        role_name = self._get_role_name(restriction)
        role = discord.utils.get(guild.roles, name=role_name)

        if not role:
            # Create roles and cache them
            roles = await self._ensure_forbid_roles(guild)
            self._roles_cache[guild.id] = (roles, now)
            role = roles.get(restriction)
        else:
            # Update cache with this role
            if guild.id in self._roles_cache:
                self._roles_cache[guild.id][0][restriction] = role
            else:
                self._roles_cache[guild.id] = ({restriction: role}, now)

        return role


__all__ = ["RolesMixin"]
