"""
AzabBot - Scheduler Mixin
=========================

Scheduled tasks: inactivity checker, title updates, auto-scan.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta, time
from typing import TYPE_CHECKING
import asyncio

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.rate_limiter import rate_limit
from src.utils.async_utils import create_safe_task

from .constants import INACTIVITY_DAYS, MAX_RETRIES

if TYPE_CHECKING:
    from .service import ModTrackerService


class SchedulerMixin:
    """Mixin for scheduled tasks."""

    # =========================================================================
    # Inactivity Checker
    # =========================================================================

    async def start_inactivity_checker(self: "ModTrackerService") -> None:
        """Start the scheduled task to check for inactive mods."""
        if not self.enabled:
            return

        create_safe_task(self._inactivity_check_loop(), "Mod Tracker Inactivity Checker")
        logger.tree("Mod Tracker: Inactivity Checker Started", [
            ("Check Time", "Daily at 12:00 PM EST"),
            ("Tracked Mods", str(len(self.db.get_all_tracked_mods()))),
        ], emoji="⏰")

    async def _inactivity_check_loop(self: "ModTrackerService") -> None:
        """Loop that checks for inactive mods daily at noon EST."""
        try:
            while True:
                try:
                    # Calculate time until next noon EST
                    now = datetime.now(NY_TZ)
                    next_check = now.replace(hour=12, minute=0, second=0, microsecond=0)
                    if next_check <= now:
                        next_check += timedelta(days=1)

                    seconds_until_check = (next_check - now).total_seconds()
                    await asyncio.sleep(seconds_until_check)

                    # Run inactivity check
                    await self._check_inactive_mods()

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Mod Tracker: Inactivity Check Error", [
                        ("Error", str(e)[:100]),
                    ])
                    await asyncio.sleep(self.config.hourly_task_interval)
        finally:
            logger.info("Mod Tracker: Inactivity Checker Stopped")

    async def _check_inactive_mods(self: "ModTrackerService") -> None:
        """Check all tracked mods for inactivity and send alerts."""
        if not self.enabled:
            return

        now = datetime.now(NY_TZ)
        cutoff_timestamp = (now - timedelta(days=INACTIVITY_DAYS)).timestamp()
        inactive_count = 0

        tracked_mods = self.db.get_all_tracked_mods()

        for mod_data in tracked_mods:
            mod_id = mod_data["mod_id"]
            last_action_at = mod_data.get("last_action_at")

            # If no recorded action, check if they were recently added
            if last_action_at is None:
                # Check created_at - if added recently, skip
                created_at = mod_data.get("created_at", 0)
                if created_at > cutoff_timestamp:
                    continue
                # Otherwise they've never had activity, alert
                days_inactive = INACTIVITY_DAYS
                last_action_str = "Never"
            else:
                if last_action_at > cutoff_timestamp:
                    continue  # Active, skip
                last_action_dt = datetime.fromtimestamp(last_action_at, tz=NY_TZ)
                days_inactive = (now - last_action_dt).days
                last_action_str = last_action_dt.strftime('%B %d, %Y')

            await self._send_alert(
                mod_id=mod_id,
                alert_type="Inactivity Warning",
                description=f"No mod actions recorded in **{days_inactive}** days\n"
                            f"Last activity: {last_action_str}",
                color=EmbedColors.ERROR,
                ping_owner=False,
            )
            inactive_count += 1
            await rate_limit("mod_tracker")

        if inactive_count > 0:
            logger.tree("Mod Tracker: Inactivity Check Complete", [
                ("Inactive Mods", str(inactive_count)),
            ], emoji="⏰")

    # =========================================================================
    # Scheduled Title Updates
    # =========================================================================

    async def start_title_update_scheduler(self: "ModTrackerService") -> None:
        """
        Start the scheduled task to update thread titles at midnight EST.
        """
        if not self.enabled:
            return

        self._scheduler_healthy = True
        create_safe_task(self._title_update_loop(), "Mod Tracker Title Update")
        logger.tree("Mod Tracker: Title Update Scheduler Started", [
            ("Update Time", "Daily at 12:00 AM EST"),
            ("Status", "Healthy"),
        ], emoji="📅")

    async def _title_update_loop(self: "ModTrackerService") -> None:
        """
        Loop that updates thread titles at 00:00 EST daily.
        """
        try:
            while True:
                try:
                    # Calculate time until next midnight EST
                    now = datetime.now(NY_TZ)
                    midnight = datetime.combine(
                        now.date() + timedelta(days=1),
                        time(0, 0),
                        tzinfo=NY_TZ,
                    )
                    seconds_until_midnight = (midnight - now).total_seconds()

                    logger.debug(f"Mod Tracker: Next scan in {seconds_until_midnight / 3600:.1f} hours")

                    # Wait until midnight
                    await asyncio.sleep(seconds_until_midnight)

                    # Run comprehensive scan
                    await self._run_comprehensive_scan()

                except asyncio.CancelledError:
                    raise  # Re-raise to exit the loop
                except Exception as e:
                    logger.error("Mod Tracker: Title Update Loop Error", [
                        ("Error", str(e)[:100]),
                    ])
                    # Wait an hour before retrying on error
                    await asyncio.sleep(self.config.hourly_task_interval)
        finally:
            self._scheduler_healthy = False
            logger.info("Mod Tracker: Scheduler stopped")

    async def _run_comprehensive_scan(self: "ModTrackerService") -> None:
        """
        Run a comprehensive scan of all moderators at midnight EST.

        This scan:
        1. Checks if tracked mods still have the mod role
        2. Removes tracking for mods who lost the role
        3. Adds tracking for new mods with the role
        4. Verifies all forum threads still exist
        5. Recreates missing threads
        6. Updates thread titles if names changed

        Also updates health tracking metrics for monitoring.
        """
        if not self.enabled:
            return

        scan_start = datetime.now(NY_TZ)
        logger.tree("Mod Tracker: Midnight Scan Starting", [
            ("Time", scan_start.strftime("%Y-%m-%d %H:%M:%S EST")),
        ], emoji="🔄")

        try:
            # -----------------------------------------------------------------
            # Get Guild and Role (mod role is in main server, not mod server)
            # -----------------------------------------------------------------

            main_guild_id = self.config.logging_guild_id or self.config.mod_server_id
            guild = self.bot.get_guild(main_guild_id)
            if not guild:
                guild = await self.bot.fetch_guild(main_guild_id)

            if not guild:
                logger.error("Mod Tracker: Midnight Scan Failed", [
                    ("Reason", "Could not access main server"),
                    ("Server ID", str(main_guild_id)),
                ])
                return

            mod_role = guild.get_role(self.config.moderation_role_id)
            if not mod_role:
                logger.error("Mod Tracker: Midnight Scan Failed", [
                    ("Reason", "Mod role not found in main server"),
                    ("Role ID", str(self.config.moderation_role_id)),
                ])
                return

            # Get current mods with role
            current_mod_ids = {m.id for m in mod_role.members}

            # Get tracked mods from database
            tracked_mods = self.db.get_all_tracked_mods()
            tracked_mod_ids = {m["mod_id"] for m in tracked_mods}

            # Stats
            removed_count = 0
            added_count = 0
            recreated_count = 0
            title_updated_count = 0
            verified_count = 0
            failed_count = 0

            # -----------------------------------------------------------------
            # Remove Mods Who Lost Role
            # -----------------------------------------------------------------

            mods_to_remove = tracked_mod_ids - current_mod_ids
            for mod_id in mods_to_remove:
                try:
                    self.db.remove_tracked_mod(mod_id)
                    removed_count += 1
                    logger.tree("Mod Tracker: Removed Ex-Mod", [
                        ("Mod ID", str(mod_id)),
                        ("Reason", "No longer has mod role"),
                    ], emoji="👋")
                except Exception as e:
                    failed_count += 1
                    logger.warning("Mod Tracker: Failed To Remove Ex-Mod", [
                        ("Mod ID", str(mod_id)),
                        ("Error", str(e)[:50]),
                    ])

            # -----------------------------------------------------------------
            # Add New Mods
            # -----------------------------------------------------------------

            mods_to_add = current_mod_ids - tracked_mod_ids
            for mod_id in mods_to_add:
                try:
                    member = guild.get_member(mod_id)
                    if not member:
                        member = await guild.fetch_member(mod_id)

                    if member:
                        thread = await self.add_tracked_mod(member)
                        if thread:
                            added_count += 1
                        else:
                            failed_count += 1
                        await rate_limit("thread_create")
                except Exception as e:
                    failed_count += 1
                    logger.warning("Mod Tracker: Failed To Add New Mod", [
                        ("Mod ID", str(mod_id)),
                        ("Error", str(e)[:50]),
                    ])

            # -----------------------------------------------------------------
            # Verify Existing Threads & Update Titles
            # -----------------------------------------------------------------

            # Refresh tracked mods after additions/removals
            tracked_mods = self.db.get_all_tracked_mods()

            for mod_data in tracked_mods:
                try:
                    mod_id = mod_data["mod_id"]
                    thread_id = mod_data["thread_id"]

                    # Get member
                    member = guild.get_member(mod_id)
                    if not member:
                        try:
                            member = await guild.fetch_member(mod_id)
                        except discord.NotFound:
                            continue

                    # Check if thread exists
                    thread = await self._get_mod_thread(thread_id)

                    if not thread:
                        # Thread was deleted, recreate it
                        logger.tree("Mod Tracker: Thread Missing, Recreating", [
                            ("Mod", member.display_name),
                            ("Mod ID", str(mod_id)),
                            ("Old Thread ID", str(thread_id)),
                        ], emoji="🔧")

                        # Remove old entry and recreate
                        self.db.remove_tracked_mod(mod_id)
                        new_thread = await self.add_tracked_mod(member)
                        if new_thread:
                            recreated_count += 1
                        else:
                            failed_count += 1
                        await rate_limit("thread_create")
                        continue

                    # Build expected name with action count and active status
                    action_count = mod_data.get("action_count") or 0
                    mod_role = guild.get_role(self.config.moderation_role_id) if guild else None
                    is_active = mod_role in member.roles if mod_role else True
                    expected_name = self._build_thread_name(member, action_count, is_active)

                    # Update title if different
                    if thread.name != expected_name:
                        old_name = thread.name
                        await thread.edit(name=expected_name)
                        title_updated_count += 1

                        logger.tree("Mod Tracker: Thread Title Updated", [
                            ("Mod", member.display_name),
                            ("Old Title", old_name[:30]),
                            ("New Title", expected_name[:30]),
                        ], emoji="✏️")

                        await rate_limit("thread_edit")
                    else:
                        verified_count += 1

                except Exception as e:
                    failed_count += 1
                    logger.warning("Mod Tracker: Failed To Verify Thread", [
                        ("Mod ID", str(mod_data.get("mod_id", "?"))),
                        ("Error", str(e)[:50]),
                    ])

            # -----------------------------------------------------------------
            # Log Summary & Update Health Metrics
            # -----------------------------------------------------------------

            scan_duration = (datetime.now(NY_TZ) - scan_start).total_seconds()

            logger.tree("Mod Tracker: Midnight Scan Complete", [
                ("Removed (lost role)", str(removed_count)),
                ("Added (new mods)", str(added_count)),
                ("Recreated (missing)", str(recreated_count)),
                ("Titles Updated", str(title_updated_count)),
                ("Verified OK", str(verified_count)),
                ("Failed", str(failed_count)),
                ("Total Tracked", str(len(self.db.get_all_tracked_mods()))),
                ("Duration", f"{scan_duration:.1f}s"),
            ], emoji="✅")

            # Run maintenance scan (cleanup duplicates & orphans)
            try:
                maint = await self.run_maintenance_scan()
                if maint.get("duplicates_deleted", 0) > 0 or maint.get("orphan_threads_deleted", 0) > 0:
                    logger.tree("Mod Tracker: Maintenance Cleanup", [
                        ("Duplicates", str(maint.get("duplicates_deleted", 0))),
                        ("Orphans", str(maint.get("orphan_threads_deleted", 0))),
                    ], emoji="🧹")
            except Exception as me:
                logger.debug(f"Maintenance scan failed: {me}")

            # Update health metrics on success
            self._last_scan_time = datetime.now(NY_TZ)
            self._consecutive_failures = 0

        except Exception as e:
            # Increment failure counter
            self._consecutive_failures += 1

            logger.error("Mod Tracker: Midnight Scan Failed", [
                ("Error", str(e)[:100]),
                ("Consecutive Failures", str(self._consecutive_failures)),
            ])

            # Self-healing: invalidate cache after multiple failures
            if self._consecutive_failures >= MAX_RETRIES:
                self.invalidate_cache()
                logger.warning("Mod Tracker: Cache invalidated after consecutive failures")

    # =========================================================================
    # Auto-Scan on Startup
    # =========================================================================

    async def auto_scan_mods(self: "ModTrackerService") -> None:
        """
        Automatically scan and create tracking threads for all mods with the mod role.

        DESIGN:
            Called on bot startup. Scans the mod server for members with the
            configured mod role and creates tracking threads for any not already tracked.
        """
        if not self.enabled:
            logger.info("Mod Tracker: Auto-scan skipped (not enabled)")
            return

        try:
            # Mod role is in main server, not mod tracker server
            main_guild_id = self.config.logging_guild_id or self.config.mod_server_id
            guild = self.bot.get_guild(main_guild_id)
            if not guild:
                guild = await self.bot.fetch_guild(main_guild_id)

            if not guild:
                logger.error("Mod Tracker: Failed To Get Main Server", [
                    ("Server ID", str(main_guild_id)),
                ])
                return

            mod_role = guild.get_role(self.config.moderation_role_id)
            if not mod_role:
                logger.error("Mod Tracker: Mod Role Not Found", [
                    ("Role ID", str(self.config.moderation_role_id)),
                    ("Server ID", str(main_guild_id)),
                ])
                return

            # Get all members with the mod role
            mods_added = 0
            mods_existing = 0
            mods_failed = 0

            for member in mod_role.members:
                if self.is_tracked(member.id):
                    mods_existing += 1
                    continue

                # Add to tracking
                thread = await self.add_tracked_mod(member)
                if thread:
                    mods_added += 1
                else:
                    mods_failed += 1

            logger.tree("Mod Tracker: Auto-Scan Complete", [
                ("Role", mod_role.name),
                ("New Mods Added", str(mods_added)),
                ("Already Tracked", str(mods_existing)),
                ("Failed", str(mods_failed)),
                ("Total Mods", str(len(mod_role.members))),
            ], emoji="👁️")

            # Run maintenance on startup
            try:
                maint = await self.run_maintenance_scan()
                if maint.get("duplicates_deleted", 0) > 0 or maint.get("orphan_threads_deleted", 0) > 0:
                    logger.tree("Mod Tracker: Startup Cleanup", [
                        ("Duplicates", str(maint.get("duplicates_deleted", 0))),
                        ("Orphans", str(maint.get("orphan_threads_deleted", 0))),
                    ], emoji="🧹")
            except Exception as me:
                logger.debug(f"Startup maintenance failed: {me}")

        except Exception as e:
            logger.error("Mod Tracker: Auto-Scan Failed", [
                ("Error", str(e)[:100]),
            ])


__all__ = ["SchedulerMixin"]
