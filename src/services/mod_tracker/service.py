"""
Azab Discord Bot - Mod Tracker Service
=======================================

Service for tracking moderator activities in a separate server forum.

DESIGN:
    Each tracked mod gets a forum thread where all their activities
    are logged: avatar changes, name changes, message edits/deletes, etc.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta, time
from typing import TYPE_CHECKING, Optional, List, Tuple, Callable, Any, Dict
from collections import defaultdict
import asyncio
import io
import re

import aiohttp
import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.views import CASE_EMOJI, MESSAGE_EMOJI, CaseButtonView, MessageButtonView

# Import from local package modules
from .constants import (
    MAX_RETRIES,
    BASE_RETRY_DELAY,
    RATE_LIMIT_DELAY,
    CACHE_TTL,
    INACTIVITY_DAYS,
    MESSAGE_CACHE_SIZE,
    MESSAGE_CACHE_TTL,
    BULK_ACTION_WINDOW,
    BULK_BAN_THRESHOLD,
    BULK_DELETE_THRESHOLD,
    BULK_TIMEOUT_THRESHOLD,
    SUSPICIOUS_UNBAN_WINDOW,
    BAN_HISTORY_TTL,
    MASS_PERMISSION_WINDOW,
    MASS_PERMISSION_THRESHOLD,
)
from .helpers import CachedMessage, strip_emojis, retry_async
from .logs import ModTrackerLogsMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Mod Tracker Service
# =============================================================================

class ModTrackerService(ModTrackerLogsMixin):
    """
    Service for tracking moderator activities.

    DESIGN:
        Each tracked mod has a forum thread in the mod server.
        All activities are logged to their thread with embeds.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
        _forum: Cached forum channel reference.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the mod tracker service.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._forum: Optional[discord.ForumChannel] = None
        self._forum_cached_at: Optional[datetime] = None
        self._scheduler_healthy: bool = False
        self._last_scan_time: Optional[datetime] = None
        self._consecutive_failures: int = 0

        # Inactivity tracking: mod_id -> last action time
        self._last_action: Dict[int, datetime] = {}

        # Message cache: mod_id -> list of cached messages
        self._message_cache: Dict[int, List[CachedMessage]] = defaultdict(list)

        # Bulk action tracking: mod_id -> action_type -> list of timestamps
        self._action_history: Dict[int, Dict[str, List[datetime]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Ban history for suspicious pattern detection: mod_id -> {target_id: ban_time}
        self._ban_history: Dict[int, Dict[int, datetime]] = defaultdict(dict)

        # Permission change tracking: mod_id -> list of timestamps
        self._permission_changes: Dict[int, List[datetime]] = defaultdict(list)

        logger.tree("Mod Tracker Service Created", [
            ("Enabled", str(self.enabled)),
        ], emoji="👁️")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if mod tracking is enabled."""
        return (
            self.config.mod_server_id is not None and
            self.config.mod_tracker_forum_id is not None and
            self.config.mod_role_id is not None
        )

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self) -> dict:
        """
        Check the health of the mod tracker service.

        Returns:
            Dict with health status info including:
            - enabled: Whether service is configured
            - forum_accessible: Whether forum channel is reachable
            - scheduler_healthy: Whether scheduler is running
            - last_scan_time: When last scan ran
            - consecutive_failures: Number of consecutive failures
            - tracked_mods_count: Number of tracked moderators
        """
        health = {
            "enabled": self.enabled,
            "forum_accessible": False,
            "scheduler_healthy": self._scheduler_healthy,
            "last_scan_time": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "consecutive_failures": self._consecutive_failures,
            "tracked_mods_count": 0,
        }

        if not self.enabled:
            return health

        # Check forum accessibility
        try:
            forum = await self._get_forum()
            health["forum_accessible"] = forum is not None
        except Exception:
            health["forum_accessible"] = False

        # Count tracked mods
        try:
            tracked = self.db.get_all_tracked_mods()
            health["tracked_mods_count"] = len(tracked)
        except Exception:
            pass

        return health

    def invalidate_cache(self) -> None:
        """
        Invalidate all cached data.

        Useful for recovery after errors or manual refresh.
        """
        self._forum = None
        self._forum_cached_at = None
        logger.info("Mod Tracker: Cache invalidated")

    # =========================================================================
    # Message Caching
    # =========================================================================

    async def cache_message(self, message: discord.Message) -> None:
        """
        Cache a message from a tracked mod with its attachments.

        Args:
            message: The message to cache.
        """
        if not self.is_tracked(message.author.id):
            return

        # Download attachments
        attachment_data: List[Tuple[str, bytes]] = []
        if message.attachments:
            async with aiohttp.ClientSession() as session:
                for attachment in message.attachments[:5]:
                    try:
                        if attachment.content_type and any(
                            t in attachment.content_type
                            for t in ["image", "video", "gif"]
                        ):
                            async with session.get(attachment.url) as resp:
                                if resp.status == 200:
                                    data = await resp.read()
                                    attachment_data.append((attachment.filename, data))
                    except Exception:
                        pass

        # Create cached message
        cached = CachedMessage(
            message_id=message.id,
            author_id=message.author.id,
            channel_id=message.channel.id,
            content=message.content or "",
            cached_at=datetime.now(NY_TZ),
            attachments=attachment_data,
        )

        # Add to cache
        mod_cache = self._message_cache[message.author.id]
        mod_cache.append(cached)

        # Trim cache if too large
        if len(mod_cache) > MESSAGE_CACHE_SIZE:
            self._message_cache[message.author.id] = mod_cache[-MESSAGE_CACHE_SIZE:]

        # Clean old messages
        cutoff = datetime.now(NY_TZ) - timedelta(seconds=MESSAGE_CACHE_TTL)
        self._message_cache[message.author.id] = [
            m for m in self._message_cache[message.author.id]
            if m.cached_at > cutoff
        ]

    def get_cached_message(self, message_id: int) -> Optional[CachedMessage]:
        """Get a cached message by ID."""
        for mod_cache in self._message_cache.values():
            for msg in mod_cache:
                if msg.message_id == message_id:
                    return msg
        return None

    # =========================================================================
    # Bulk Action Detection
    # =========================================================================

    def _record_action(self, mod_id: int, action_type: str) -> None:
        """
        Record an action for bulk detection and update last activity.

        Args:
            mod_id: The moderator's ID.
            action_type: Type of action (ban, timeout, delete, etc.)
        """
        now = datetime.now(NY_TZ)

        # Update last action time
        self._last_action[mod_id] = now

        # Record for bulk detection
        self._action_history[mod_id][action_type].append(now)

        # Clean old entries outside the window
        cutoff = now - timedelta(seconds=BULK_ACTION_WINDOW)
        self._action_history[mod_id][action_type] = [
            t for t in self._action_history[mod_id][action_type]
            if t > cutoff
        ]

    async def _check_bulk_action(self, mod_id: int, action_type: str) -> None:
        """
        Check if bulk action threshold exceeded, send alert, and remove mod role.

        Args:
            mod_id: The moderator's ID.
            action_type: Type of action to check.
        """
        count = len(self._action_history[mod_id][action_type])

        threshold = None
        if action_type == "ban":
            threshold = BULK_BAN_THRESHOLD
        elif action_type == "timeout":
            threshold = BULK_TIMEOUT_THRESHOLD
        elif action_type == "delete":
            threshold = BULK_DELETE_THRESHOLD

        if threshold and count >= threshold:
            # Remove mod role first
            role_removed = await self._remove_mod_role(mod_id)

            # Send alert
            description = f"**{count}** {action_type}s in the last 5 minutes"
            if role_removed:
                description += "\n\n**⚠️ Mod role has been automatically removed.**"

            await self._send_alert(
                mod_id=mod_id,
                alert_type="Bulk Action Detected",
                description=description,
                color=EmbedColors.ERROR,
            )

            # Clear after alerting to avoid spam
            self._action_history[mod_id][action_type].clear()

    async def _remove_mod_role(self, mod_id: int) -> bool:
        """
        Remove the mod role from a user.

        Args:
            mod_id: The moderator's ID.

        Returns:
            True if role was removed, False otherwise.
        """
        if not self.config.mod_role_id:
            return False

        try:
            # Mod role is in main server
            main_guild_id = self.config.logging_guild_id or self.config.mod_server_id
            guild = self.bot.get_guild(main_guild_id)
            if not guild:
                return False

            member = guild.get_member(mod_id)
            if not member:
                return False

            role = guild.get_role(self.config.mod_role_id)
            if not role:
                return False

            await member.remove_roles(role, reason="Bulk action detected - automatic removal")

            logger.tree("Mod Tracker: Mod Role Removed", [
                ("Mod", str(member)),
                ("Mod ID", str(mod_id)),
                ("Reason", "Bulk action detected"),
            ], emoji="🚨")

            return True

        except discord.Forbidden:
            logger.error("Mod Tracker: No Permission To Remove Role", [
                ("Mod ID", str(mod_id)),
            ])
            return False
        except Exception as e:
            logger.error("Mod Tracker: Failed To Remove Role", [
                ("Mod ID", str(mod_id)),
                ("Error", str(e)[:50]),
            ])
            return False

    async def _send_alert(
        self,
        mod_id: int,
        alert_type: str,
        description: str,
        color: int = EmbedColors.WARNING,
    ) -> None:
        """
        Send an alert to a mod's thread with ping.

        Args:
            mod_id: The moderator's ID.
            alert_type: Type of alert for the title.
            description: Alert description.
            color: Embed color.
        """
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return

        thread = await self._get_mod_thread(tracked["thread_id"])
        if not thread:
            return

        embed = discord.Embed(
            title=f"⚠️ {alert_type}",
            description=description,
            color=color,
            timestamp=datetime.now(NY_TZ),
        )
        embed.set_footer(text=f"Alert • Mod ID: {mod_id}")

        try:
            if thread.archived:
                await thread.edit(archived=False)
                await asyncio.sleep(RATE_LIMIT_DELAY)

            await thread.send(
                content=f"<@{self.config.developer_id}>",
                embed=embed,
            )

            logger.tree("Mod Tracker: Alert Sent", [
                ("Mod ID", str(mod_id)),
                ("Type", alert_type),
            ], emoji="⚠️")

        except Exception as e:
            logger.error("Mod Tracker: Failed To Send Alert", [
                ("Mod ID", str(mod_id)),
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Inactivity Checker
    # =========================================================================

    async def start_inactivity_checker(self) -> None:
        """Start the scheduled task to check for inactive mods."""
        if not self.enabled:
            return

        asyncio.create_task(self._inactivity_check_loop())
        logger.tree("Mod Tracker: Inactivity Checker Started", [
            ("Check Time", "Daily at 12:00 PM EST"),
            ("Tracked Mods", str(len(self._tracked_mods))),
        ], emoji="⏰")

    async def _inactivity_check_loop(self) -> None:
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

    async def _check_inactive_mods(self) -> None:
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
            )
            inactive_count += 1
            await asyncio.sleep(RATE_LIMIT_DELAY)

        if inactive_count > 0:
            logger.tree("Mod Tracker: Inactivity Check Complete", [
                ("Inactive Mods", str(inactive_count)),
            ], emoji="⏰")

    # =========================================================================
    # Peak Hours Formatter
    # =========================================================================

    def _format_peak_hours(self, mod_id: int) -> str:
        """
        Format peak activity hours for display.

        Args:
            mod_id: The moderator's ID.

        Returns:
            Formatted string like "2 PM (45), 8 PM (32), 10 PM (28)" or "No data yet".
        """
        peak_hours = self.db.get_peak_hours(mod_id, top_n=3)
        if not peak_hours:
            return "No data yet"

        formatted = []
        for hour, count in peak_hours:
            # Convert 24h to 12h format
            if hour == 0:
                time_str = "12 AM"
            elif hour < 12:
                time_str = f"{hour} AM"
            elif hour == 12:
                time_str = "12 PM"
            else:
                time_str = f"{hour - 12} PM"
            formatted.append(f"{time_str} ({count})")

        return ", ".join(formatted)

    # =========================================================================
    # Thread Name Builder
    # =========================================================================

    def _build_thread_name(
        self,
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
    # Scheduled Title Updates
    # =========================================================================

    async def start_title_update_scheduler(self) -> None:
        """
        Start the scheduled task to update thread titles at midnight EST.
        """
        if not self.enabled:
            return

        self._scheduler_healthy = True
        asyncio.create_task(self._title_update_loop())
        logger.tree("Mod Tracker: Title Update Scheduler Started", [
            ("Update Time", "Daily at 12:00 AM EST"),
            ("Status", "Healthy"),
        ], emoji="📅")

    async def _title_update_loop(self) -> None:
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

    async def _run_comprehensive_scan(self) -> None:
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
            # -------------------------------------------------------------
            # Get Guild and Role (mod role is in main server, not mod server)
            # -------------------------------------------------------------

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

            mod_role = guild.get_role(self.config.mod_role_id)
            if not mod_role:
                logger.error("Mod Tracker: Midnight Scan Failed", [
                    ("Reason", "Mod role not found in main server"),
                    ("Role ID", str(self.config.mod_role_id)),
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

            # -------------------------------------------------------------
            # Remove Mods Who Lost Role
            # -------------------------------------------------------------

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

            # -------------------------------------------------------------
            # Add New Mods
            # -------------------------------------------------------------

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
                        await asyncio.sleep(self.config.rate_limit_delay)  # Rate limit
                except Exception as e:
                    failed_count += 1
                    logger.warning("Mod Tracker: Failed To Add New Mod", [
                        ("Mod ID", str(mod_id)),
                        ("Error", str(e)[:50]),
                    ])

            # -------------------------------------------------------------
            # Verify Existing Threads & Update Titles
            # -------------------------------------------------------------

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
                        await asyncio.sleep(self.config.rate_limit_delay)
                        continue

                    # Build expected name with action count and active status
                    action_count = mod_data.get("action_count") or 0
                    mod_role = guild.get_role(self.config.mod_role_id) if guild else None
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

                        await asyncio.sleep(self.config.rate_limit_delay)  # Rate limit
                    else:
                        verified_count += 1

                except Exception as e:
                    failed_count += 1
                    logger.warning("Mod Tracker: Failed To Verify Thread", [
                        ("Mod ID", str(mod_data.get("mod_id", "?"))),
                        ("Error", str(e)[:50]),
                    ])

            # -------------------------------------------------------------
            # Log Summary & Update Health Metrics
            # -------------------------------------------------------------

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

    async def auto_scan_mods(self) -> None:
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

            mod_role = guild.get_role(self.config.mod_role_id)
            if not mod_role:
                logger.error("Mod Tracker: Mod Role Not Found", [
                    ("Role ID", str(self.config.mod_role_id)),
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

        except Exception as e:
            logger.error("Mod Tracker: Auto-Scan Failed", [
                ("Error", str(e)[:100]),
            ])

    # =========================================================================
    # Forum Access
    # =========================================================================

    async def _get_forum(self) -> Optional[discord.ForumChannel]:
        """
        Get the mod tracker forum channel with cache TTL.

        Returns:
            Forum channel or None.
        """
        if not self.config.mod_tracker_forum_id:
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
                channel = self.bot.get_channel(self.config.mod_tracker_forum_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(self.config.mod_tracker_forum_id)
                if isinstance(channel, discord.ForumChannel):
                    self._forum = channel
                    self._forum_cached_at = datetime.now(NY_TZ)
                    logger.debug(f"Mod Tracker: Forum Channel Cached (ID: {self.config.mod_tracker_forum_id})")
            except discord.NotFound:
                logger.error("Mod Tracker: Forum Not Found", [
                    ("Forum ID", str(self.config.mod_tracker_forum_id)),
                ])
                return None
            except discord.Forbidden:
                logger.error("Mod Tracker: No Permission To Access Forum", [
                    ("Forum ID", str(self.config.mod_tracker_forum_id)),
                ])
                return None
            except Exception as e:
                logger.error("Mod Tracker: Failed To Get Forum", [
                    ("Forum ID", str(self.config.mod_tracker_forum_id)),
                    ("Error", str(e)[:50]),
                ])
                return None

        return self._forum

    async def _get_mod_thread(self, thread_id: int) -> Optional[discord.Thread]:
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
    # Embed Builder Helpers
    # =========================================================================

    def _create_embed(
        self,
        title: str,
        color: int = EmbedColors.INFO,
    ) -> discord.Embed:
        """
        Create a standardized embed with NY timezone.

        Args:
            title: Embed title.
            color: Embed color.

        Returns:
            Configured embed.
        """
        now = datetime.now(NY_TZ)
        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=now,
        )
        return embed

    def _add_mod_field(
        self,
        embed: discord.Embed,
        mod: discord.Member,
    ) -> None:
        """
        Add moderator info field to embed.

        Args:
            embed: The embed to modify.
            mod: The moderator.
        """
        embed.set_author(
            name=f"{mod.display_name}",
            icon_url=mod.display_avatar.url,
        )

    # =========================================================================
    # Mod Management
    # =========================================================================

    async def add_tracked_mod(self, mod: discord.Member) -> Optional[discord.Thread]:
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

    async def remove_tracked_mod(self, mod_id: int) -> bool:
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

    def is_tracked(self, user_id: int) -> bool:
        """Check if a user is being tracked."""
        return self.db.get_tracked_mod(user_id) is not None

    # =========================================================================
    # Send Log Helper
    # =========================================================================

    async def _send_log(
        self,
        mod_id: int,
        embed: discord.Embed,
        action_name: str,
        view: Optional[discord.ui.View] = None,
    ) -> bool:
        """
        Send a log embed to a mod's tracking thread.

        Automatically unarchives threads if needed and updates thread title.

        Args:
            mod_id: The moderator's ID.
            embed: The embed to send.
            action_name: Name of the action for logging.
            view: Optional view with buttons.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.enabled:
            return False

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return False

        thread = await self._get_mod_thread(tracked["thread_id"])
        if not thread:
            return False

        try:
            # Unarchive if thread is archived
            if thread.archived:
                try:
                    await thread.edit(archived=False)
                    logger.debug(f"Mod Tracker: Unarchived thread for mod {mod_id}")
                    await asyncio.sleep(RATE_LIMIT_DELAY)
                except discord.HTTPException as e:
                    logger.warning("Mod Tracker: Failed To Unarchive Thread", [
                        ("Mod ID", str(mod_id)),
                        ("Error", str(e)[:50]),
                    ])
                    # Continue anyway - might still work

            await thread.send(embed=embed, view=view)

            # Increment action count and update thread title
            new_count = self.db.increment_mod_action_count(mod_id)

            # Track hourly activity
            current_hour = datetime.now(NY_TZ).hour
            self.db.increment_hourly_activity(mod_id, current_hour)

            # Get mod member to build new thread name
            main_guild_id = self.config.logging_guild_id or self.config.mod_server_id
            main_guild = self.bot.get_guild(main_guild_id)
            if main_guild:
                mod_member = main_guild.get_member(mod_id)
                if mod_member:
                    # Check if mod still has mod role
                    mod_role = main_guild.get_role(self.config.mod_role_id)
                    is_active = mod_role in mod_member.roles if mod_role else True

                    new_name = self._build_thread_name(mod_member, new_count, is_active)
                    if thread.name != new_name:
                        try:
                            await thread.edit(name=new_name)
                        except discord.HTTPException:
                            pass  # Ignore rate limits on title updates

            logger.debug(f"Mod Tracker: Log Sent - Mod {mod_id}, Action: {action_name}")
            return True
        except discord.Forbidden:
            logger.error("Mod Tracker: No Permission To Send Log", [
                ("Mod ID", str(mod_id)),
                ("Action", action_name),
            ])
            return False
        except discord.HTTPException as e:
            logger.error("Mod Tracker: HTTP Error Sending Log", [
                ("Mod ID", str(mod_id)),
                ("Action", action_name),
                ("Error", str(e)[:50]),
            ])
            return False
        except Exception as e:
            logger.error("Mod Tracker: Failed To Send Log", [
                ("Mod ID", str(mod_id)),
                ("Action", action_name),
                ("Error", str(e)[:50]),
            ])
            return False

