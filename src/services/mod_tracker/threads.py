"""
AzabBot - Threads Mixin
=======================

Forum and thread management operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.core.constants import QUERY_LIMIT_XL

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
                logger.debug("Mod Tracker Forum Cache Expired", [("Age", f"{cache_age:.0f}s")])
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
                    logger.debug("Mod Tracker Forum Cached", [("ID", str(self.config.mod_logs_forum_id))])
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
            logger.debug("Mod Tracker Mod Already Tracked", [("Mod", mod.display_name), ("ID", str(mod.id))])
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
            logger.debug("Mod Tracker Mod Not Found", [("ID", str(mod_id))])
        return removed

    def is_tracked(self: "ModTrackerService", user_id: int) -> bool:
        """Check if a user is being tracked."""
        return self.db.get_tracked_mod(user_id) is not None

    # =========================================================================
    # Role Loss Handling
    # =========================================================================

    async def handle_mod_role_removed(
        self: "ModTrackerService",
        member: discord.Member,
    ) -> bool:
        """
        Handle when a mod loses their moderation role.
        Deletes their tracking thread and removes from database.
        """
        if not self.enabled:
            return False

        logger.tree("Mod Tracker: Role Removal Detected", [
            ("Mod", f"{member.display_name}"),
            ("Mod ID", str(member.id)),
        ], emoji="👋")

        tracked = self.db.get_tracked_mod(member.id)
        if not tracked:
            logger.debug("Mod Tracker Mod Not Tracked", [("ID", str(member.id))])
            return False

        thread_id = tracked.get("thread_id")
        if not thread_id:
            self.db.remove_tracked_mod(member.id)
            logger.tree("Mod Tracker: DB Entry Removed (No Thread)", [
                ("Mod", f"{member.display_name}"),
                ("Mod ID", str(member.id)),
            ], emoji="🗑️")
            return False

        try:
            thread = await self._get_mod_thread(thread_id)
            if thread:
                await thread.delete(reason=f"Mod role removed from {member.display_name}")
                logger.tree("Mod Tracker: Thread Deleted (Role Removed)", [
                    ("Mod", f"{member.display_name}"),
                    ("Mod ID", str(member.id)),
                    ("Thread ID", str(thread_id)),
                    ("Thread Name", thread.name[:50] if thread.name else "Unknown"),
                ], emoji="🗑️")
            else:
                logger.tree("Mod Tracker: Thread Already Gone", [
                    ("Mod", f"{member.display_name}"),
                    ("Thread ID", str(thread_id)),
                ], emoji="ℹ️")
        except discord.NotFound:
            logger.tree("Mod Tracker: Thread Not Found (Already Deleted)", [
                ("Mod", f"{member.display_name}"),
                ("Thread ID", str(thread_id)),
            ], emoji="ℹ️")
        except discord.Forbidden:
            logger.error("Mod Tracker: No Permission To Delete Thread", [
                ("Mod", f"{member.display_name}"),
                ("Thread ID", str(thread_id)),
            ])
        except Exception as e:
            logger.error("Mod Tracker: Thread Delete Failed", [
                ("Mod", f"{member.display_name}"),
                ("Thread ID", str(thread_id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])

        self.db.remove_tracked_mod(member.id)
        logger.tree("Mod Tracker: Cleanup Complete", [
            ("Mod", f"{member.display_name}"),
            ("Mod ID", str(member.id)),
            ("Action", "Thread deleted + DB entry removed"),
        ], emoji="✅")
        return True

    # =========================================================================
    # Maintenance & Cleanup
    # =========================================================================

    async def run_maintenance_scan(self: "ModTrackerService") -> dict:
        """
        Run maintenance scan - cleanup duplicates and orphan threads.
        """
        if not self.enabled:
            logger.debug("Mod Tracker: Maintenance scan skipped (not enabled)")
            return {"error": "Not enabled"}

        logger.tree("Mod Tracker: Maintenance Scan Starting", [], emoji="🔍")

        forum = await self._get_forum()
        if not forum:
            logger.warning("Mod Tracker: Maintenance scan aborted (forum not found)")
            return {"error": "Forum not found"}

        stats = {
            "threads_scanned": 0,
            "duplicates_deleted": 0,
            "orphan_threads_deleted": 0,
            "orphan_db_entries_removed": 0,
            "errors": 0,
        }

        all_tracked = self.db.get_all_tracked_mods()
        tracked_by_id = {t["mod_id"]: t for t in all_tracked}

        logger.debug("Mod Tracker Database", [("Tracked Mods", str(len(all_tracked)))])

        # Collect threads
        all_threads = list(forum.threads)
        try:
            async for thread in forum.archived_threads(limit=QUERY_LIMIT_XL):
                all_threads.append(thread)
        except Exception as e:
            logger.warning("Mod Tracker: Failed to fetch archived threads", [
                ("Error", str(e)[:50]),
            ])

        stats["threads_scanned"] = len(all_threads)
        logger.debug("Mod Tracker Scanning Threads", [("Count", str(len(all_threads)))])

        # Group by mod
        threads_by_mod = {}
        orphan_threads = []

        for thread in all_threads:
            mod_id = None
            for m_id, tracked in tracked_by_id.items():
                if tracked["thread_id"] == thread.id:
                    mod_id = m_id
                    break

            if mod_id:
                if mod_id not in threads_by_mod:
                    threads_by_mod[mod_id] = []
                threads_by_mod[mod_id].append(thread)
            else:
                orphan_threads.append(thread)

        # Delete duplicates (keep newest)
        for mod_id, threads in threads_by_mod.items():
            if len(threads) > 1:
                threads.sort(key=lambda t: t.id, reverse=True)
                kept_thread = threads[0]
                self.db.update_tracked_mod_thread(mod_id, kept_thread.id)

                logger.tree("Mod Tracker: Duplicate Threads Found", [
                    ("Mod ID", str(mod_id)),
                    ("Total Threads", str(len(threads))),
                    ("Keeping", f"{kept_thread.name[:30]} (ID: {kept_thread.id})"),
                ], emoji="🔄")

                for old_thread in threads[1:]:
                    try:
                        await old_thread.delete(reason="Maintenance: Duplicate cleanup")
                        stats["duplicates_deleted"] += 1
                        logger.tree("Mod Tracker: Duplicate Thread Deleted", [
                            ("Mod ID", str(mod_id)),
                            ("Thread ID", str(old_thread.id)),
                            ("Thread Name", old_thread.name[:40] if old_thread.name else "Unknown"),
                        ], emoji="🗑️")
                    except discord.NotFound:
                        logger.debug("Mod Tracker Duplicate Already Deleted", [("Thread", str(old_thread.id))])
                    except discord.Forbidden:
                        stats["errors"] += 1
                        logger.error("Mod Tracker: No Permission To Delete Duplicate", [
                            ("Thread ID", str(old_thread.id)),
                        ])
                    except Exception as e:
                        stats["errors"] += 1
                        logger.error("Mod Tracker: Failed To Delete Duplicate", [
                            ("Thread ID", str(old_thread.id)),
                            ("Error", str(e)[:50]),
                        ])

        # Delete orphan threads (threads that look like mod tracker threads but aren't in DB)
        for thread in orphan_threads:
            if " | " in thread.name and ("action" in thread.name.lower() or "active" in thread.name.lower()):
                try:
                    await thread.delete(reason="Maintenance: Orphan cleanup")
                    stats["orphan_threads_deleted"] += 1
                    logger.tree("Mod Tracker: Orphan Thread Deleted", [
                        ("Thread ID", str(thread.id)),
                        ("Thread Name", thread.name[:40] if thread.name else "Unknown"),
                        ("Reason", "Not linked to any tracked mod"),
                    ], emoji="🗑️")
                except discord.NotFound:
                    logger.debug("Mod Tracker Orphan Already Deleted", [("Thread", str(thread.id))])
                except discord.Forbidden:
                    stats["errors"] += 1
                    logger.error("Mod Tracker: No Permission To Delete Orphan", [
                        ("Thread ID", str(thread.id)),
                    ])
                except Exception as e:
                    stats["errors"] += 1
                    logger.error("Mod Tracker: Failed To Delete Orphan Thread", [
                        ("Thread ID", str(thread.id)),
                        ("Error", str(e)[:50]),
                    ])

        # Clean orphan DB entries (DB entries pointing to non-existent threads)
        existing_ids = {t.id for t in all_threads}
        for tracked in all_tracked:
            if tracked["thread_id"] not in existing_ids:
                self.db.remove_tracked_mod(tracked["mod_id"])
                stats["orphan_db_entries_removed"] += 1
                logger.tree("Mod Tracker: Orphan DB Entry Removed", [
                    ("Mod ID", str(tracked["mod_id"])),
                    ("Missing Thread ID", str(tracked["thread_id"])),
                    ("Display Name", tracked.get("display_name", "Unknown")[:30]),
                ], emoji="🗑️")

        logger.tree("Mod Tracker: Maintenance Complete", [
            ("Threads Scanned", str(stats["threads_scanned"])),
            ("Duplicates Deleted", str(stats["duplicates_deleted"])),
            ("Orphan Threads Deleted", str(stats["orphan_threads_deleted"])),
            ("Orphan DB Entries Removed", str(stats["orphan_db_entries_removed"])),
            ("Errors", str(stats["errors"])),
        ], emoji="🧹")

        return stats


__all__ = ["ThreadsMixin"]
