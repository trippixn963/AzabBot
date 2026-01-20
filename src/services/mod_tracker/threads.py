"""
Mod Tracker - Threads Mixin
===========================

Forum and thread management operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ

from .constants import CACHE_TTL
from .helpers import strip_emojis

if TYPE_CHECKING:
    from .service import ModTrackerService


class ThreadsMixin:
    """Mixin for forum and thread management."""

    # =========================================================================
    # Forum Access
    # =========================================================================

    async def _get_forum(self: "ModTrackerService") -> Optional[discord.ForumChannel]:
        """
        Get the mod tracker forum channel with cache TTL.

        Returns:
            Forum channel or None.
        """
        if not self.config.mod_logs_forum_id:
            return None

        # Check if cache is stale
        now = datetime.now(NY_TZ)
        if self._forum is not None and self._forum_cached_at is not None:
            cache_age = (now - self._forum_cached_at).total_seconds()
            if cache_age > CACHE_TTL:
                logger.debug(f"Mod Tracker: Forum cache expired (age: {cache_age:.0f}s)")
                self._forum = None
                self._forum_cached_at = None

        if self._forum is None:
            try:
                channel = self.bot.get_channel(self.config.mod_logs_forum_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(self.config.mod_logs_forum_id)
                if isinstance(channel, discord.ForumChannel):
                    self._forum = channel
                    self._forum_cached_at = datetime.now(NY_TZ)
                    logger.debug(f"Mod Tracker: Forum Channel Cached (ID: {self.config.mod_logs_forum_id})")
            except discord.NotFound:
                logger.error("Mod Tracker: Forum Not Found", [
                    ("Forum ID", str(self.config.mod_logs_forum_id)),
                ])
                return None
            except discord.Forbidden:
                logger.error("Mod Tracker: No Permission To Access Forum", [
                    ("Forum ID", str(self.config.mod_logs_forum_id)),
                ])
                return None
            except Exception as e:
                logger.error("Mod Tracker: Failed To Get Forum", [
                    ("Forum ID", str(self.config.mod_logs_forum_id)),
                    ("Error", str(e)[:50]),
                ])
                return None

        return self._forum

    async def _get_mod_thread(
        self: "ModTrackerService",
        thread_id: int
    ) -> Optional[discord.Thread]:
        """
        Get a mod's tracking thread by ID.

        Args:
            thread_id: The thread ID.

        Returns:
            The thread, or None if not found.
        """
        try:
            thread = self.bot.get_channel(thread_id)
            if thread is None:
                thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                return thread
        except discord.NotFound:
            logger.warning("Mod Tracker: Thread Not Found", [
                ("Thread ID", str(thread_id)),
            ])
        except discord.Forbidden:
            logger.warning("Mod Tracker: No Permission To Access Thread", [
                ("Thread ID", str(thread_id)),
            ])
        except Exception as e:
            logger.warning("Mod Tracker: Failed To Get Thread", [
                ("Thread ID", str(thread_id)),
                ("Error", str(e)[:50]),
            ])
        return None

    # =========================================================================
    # Thread Name Builder
    # =========================================================================

    def _build_thread_name(
        self: "ModTrackerService",
        mod: discord.Member,
        action_count: int = 0,
        is_active: bool = True,
    ) -> str:
        """
        Build a thread name for a mod.

        Format: ModName | 156 actions | Active

        Args:
            mod: The moderator member.
            action_count: Total actions logged for this mod.
            is_active: Whether the mod is currently active (has mod role).

        Returns:
            Formatted thread name (max 100 chars).
        """
        display_name = strip_emojis(mod.display_name or mod.name)

        # Build status string
        status = "Active" if is_active else "Inactive"

        # Build action count string
        action_str = f"{action_count} action{'s' if action_count != 1 else ''}"

        # Combine: Name | X actions | Status
        thread_name = f"{display_name} | {action_str} | {status}"

        return thread_name[:100]

    # =========================================================================
    # Mod Management
    # =========================================================================

    async def add_tracked_mod(
        self: "ModTrackerService",
        mod: discord.Member
    ) -> Optional[discord.Thread]:
        """
        Add a mod to tracking and create their thread.

        Args:
            mod: The moderator to track.

        Returns:
            The created thread, or None on failure.
        """
        if not self.enabled:
            return None

        # Check if already tracked
        existing = self.db.get_tracked_mod(mod.id)
        if existing:
            logger.debug(f"Mod Tracker: Mod Already Tracked - {mod.display_name} ({mod.id})")
            return await self._get_mod_thread(existing["thread_id"])

        forum = await self._get_forum()
        if not forum:
            return None

        # Build initial profile embed
        profile_embed = self._create_embed(
            title="👤 Moderator Profile",
            color=EmbedColors.INFO,
        )
        profile_embed.set_thumbnail(url=mod.display_avatar.url)
        profile_embed.add_field(name="Username", value=f"`{mod.name}`", inline=True)
        profile_embed.add_field(name="Display Name", value=f"`{mod.display_name}`", inline=True)
        profile_embed.add_field(name="User ID", value=f"`{mod.id}`", inline=True)

        if mod.joined_at:
            profile_embed.add_field(
                name="Server Joined",
                value=f"<t:{int(mod.joined_at.timestamp())}:F>",
                inline=True,
            )

        profile_embed.add_field(
            name="Account Created",
            value=f"<t:{int(mod.created_at.timestamp())}:F>",
            inline=True,
        )

        # Add peak hours (will show "No data yet" for new mods)
        profile_embed.add_field(
            name="🕐 Peak Hours",
            value=self._format_peak_hours(mod.id),
            inline=False,
        )

        # Build thread name using helper (new thread = 0 actions, Active)
        thread_name = self._build_thread_name(mod, action_count=0, is_active=True)

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name,
                embed=profile_embed,
            )

            # Pin the profile message
            try:
                if thread_with_msg.message:
                    await thread_with_msg.message.pin()
            except Exception as e:
                logger.warning("Mod Tracker: Failed To Pin Profile", [
                    ("Mod", f"{mod.display_name}"),
                    ("Error", str(e)[:50]),
                ])

            # Get avatar hash for change detection
            avatar_hash = mod.avatar.key if mod.avatar else None

            # Save to database
            self.db.add_tracked_mod(
                mod_id=mod.id,
                thread_id=thread_with_msg.thread.id,
                display_name=mod.display_name,
                username=mod.name,
                avatar_hash=avatar_hash,
            )

            logger.tree("Mod Tracker: Added Mod", [
                ("Mod", f"{mod.display_name}"),
                ("Mod ID", str(mod.id)),
                ("Thread ID", str(thread_with_msg.thread.id)),
            ], emoji="👁️")

            return thread_with_msg.thread

        except discord.Forbidden:
            logger.error("Mod Tracker: No Permission To Create Thread", [
                ("Mod", f"{mod.display_name} ({mod.id})"),
            ])
            return None
        except discord.HTTPException as e:
            logger.error("Mod Tracker: HTTP Error Creating Thread", [
                ("Mod", f"{mod.display_name} ({mod.id})"),
                ("Error", str(e)[:100]),
            ])
            return None
        except Exception as e:
            logger.error("Mod Tracker: Failed To Create Thread", [
                ("Mod", f"{mod.display_name} ({mod.id})"),
                ("Error", str(e)[:100]),
            ])
            return None

    async def remove_tracked_mod(self: "ModTrackerService", mod_id: int) -> bool:
        """
        Remove a mod from tracking.

        Args:
            mod_id: The mod's Discord user ID.

        Returns:
            True if removed, False if not found.
        """
        removed = self.db.remove_tracked_mod(mod_id)
        if removed:
            logger.tree("Mod Tracker: Removed Mod", [
                ("Mod ID", str(mod_id)),
            ], emoji="👁️")
        else:
            logger.debug(f"Mod Tracker: Mod Not Found For Removal - ID: {mod_id}")
        return removed

    def is_tracked(self: "ModTrackerService", user_id: int) -> bool:
        """Check if a user is being tracked."""
        return self.db.get_tracked_mod(user_id) is not None


__all__ = ["ThreadsMixin"]
