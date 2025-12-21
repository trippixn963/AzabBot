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

import aiohttp
import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db

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

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Mod Tracker Service
# =============================================================================

class ModTrackerService:
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
        if not self.config.mod_role_id or not self.config.mod_server_id:
            return False

        try:
            guild = self.bot.get_guild(self.config.mod_server_id)
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
        embed.set_footer(text=datetime.now(NY_TZ).strftime("%B %d, %Y"))

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
        logger.info("Mod Tracker: Inactivity Checker Started")

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
                    await asyncio.sleep(3600)
        finally:
            logger.info("Mod Tracker: Inactivity Checker Stopped")

    async def _check_inactive_mods(self) -> None:
        """Check all tracked mods for inactivity and send alerts."""
        if not self.enabled:
            return

        now = datetime.now(NY_TZ)
        cutoff = now - timedelta(days=INACTIVITY_DAYS)
        inactive_count = 0

        tracked_mods = self.db.get_all_tracked_mods()

        for mod_data in tracked_mods:
            mod_id = mod_data["mod_id"]
            last_action = self._last_action.get(mod_id)

            # If no recorded action, check if they were recently added
            if last_action is None:
                # Assume active if no data yet
                continue

            if last_action < cutoff:
                days_inactive = (now - last_action).days
                await self._send_alert(
                    mod_id=mod_id,
                    alert_type="Inactivity Warning",
                    description=f"No mod actions recorded in **{days_inactive}** days\n"
                                f"Last activity: {last_action.strftime('%B %d, %Y')}",
                    color=EmbedColors.ERROR,
                )
                inactive_count += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)

        if inactive_count > 0:
            logger.tree("Mod Tracker: Inactivity Check Complete", [
                ("Inactive Mods", str(inactive_count)),
            ], emoji="⏰")

    # =========================================================================
    # Thread Name Builder
    # =========================================================================

    def _build_thread_name(self, mod: discord.Member) -> str:
        """
        Build a thread name for a mod.

        Format: [username] | [display_name] or just [username] if same.

        Args:
            mod: The moderator member.

        Returns:
            Formatted thread name (max 100 chars).
        """
        username = strip_emojis(mod.name)
        display_name = strip_emojis(mod.display_name)

        if not display_name or display_name.lower() == username.lower():
            thread_name = f"[{username}]"
        else:
            thread_name = f"[{username}] | [{display_name}]"

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
        logger.info("Mod Tracker: Title Update Scheduler Started")

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
                    await asyncio.sleep(3600)
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
            # Get Guild and Role
            # -------------------------------------------------------------

            guild = self.bot.get_guild(self.config.mod_server_id)
            if not guild:
                guild = await self.bot.fetch_guild(self.config.mod_server_id)

            if not guild:
                logger.error("Mod Tracker: Midnight Scan Failed", [
                    ("Reason", "Could not access server"),
                    ("Server ID", str(self.config.mod_server_id)),
                ])
                return

            mod_role = guild.get_role(self.config.mod_role_id)
            if not mod_role:
                logger.error("Mod Tracker: Midnight Scan Failed", [
                    ("Reason", "Mod role not found"),
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
                        await asyncio.sleep(1)  # Rate limit
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
                        await asyncio.sleep(1)
                        continue

                    # Build expected name
                    expected_name = self._build_thread_name(member)

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

                        await asyncio.sleep(1)  # Rate limit
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
            guild = self.bot.get_guild(self.config.mod_server_id)
            if not guild:
                guild = await self.bot.fetch_guild(self.config.mod_server_id)

            if not guild:
                logger.error("Mod Tracker: Failed To Get Mod Server", [
                    ("Server ID", str(self.config.mod_server_id)),
                ])
                return

            mod_role = guild.get_role(self.config.mod_role_id)
            if not mod_role:
                logger.error("Mod Tracker: Mod Role Not Found", [
                    ("Role ID", str(self.config.mod_role_id)),
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
        mod_avatar_url: Optional[str] = None,
    ) -> discord.Embed:
        """
        Create a standardized embed with NY timezone.

        Args:
            title: Embed title.
            color: Embed color.
            mod_avatar_url: Optional moderator avatar URL for thumbnail.

        Returns:
            Configured embed.
        """
        now = datetime.now(NY_TZ)
        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=now,
        )

        if mod_avatar_url:
            embed.set_thumbnail(url=mod_avatar_url)

        embed.set_footer(text=now.strftime("%B %d, %Y"))
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
            title="Moderator Profile",
            color=EmbedColors.INFO,
            mod_avatar_url=mod.display_avatar.url,
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

        # Build thread name using helper
        thread_name = self._build_thread_name(mod)

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
    ) -> bool:
        """
        Send a log embed to a mod's tracking thread.

        Automatically unarchives threads if needed.

        Args:
            mod_id: The moderator's ID.
            embed: The embed to send.
            action_name: Name of the action for logging.

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

            await thread.send(embed=embed)
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

    # =========================================================================
    # Activity Logging - Personal
    # =========================================================================

    async def log_avatar_change(
        self,
        mod: discord.Member,
        old_avatar: Optional[discord.Asset],
        new_avatar: Optional[discord.Asset],
    ) -> None:
        """Log an avatar change."""
        embed = self._create_embed(
            title="Avatar Changed",
            color=EmbedColors.WARNING,
            mod_avatar_url=new_avatar.url if new_avatar else None,
        )
        self._add_mod_field(embed, mod)

        if old_avatar:
            embed.add_field(name="Old Avatar", value=f"[Link]({old_avatar.url})", inline=True)
        else:
            embed.add_field(name="Old Avatar", value="*None*", inline=True)

        if new_avatar:
            embed.add_field(name="New Avatar", value=f"[Link]({new_avatar.url})", inline=True)
        else:
            embed.add_field(name="New Avatar", value="*Removed*", inline=True)

        if await self._send_log(mod.id, embed, "Avatar Change"):
            # Update stored avatar hash
            new_hash = mod.avatar.key if mod.avatar else None
            self.db.update_mod_info(mod.id, avatar_hash=new_hash)

            logger.tree("Mod Tracker: Avatar Change Logged", [
                ("Mod", mod.display_name),
            ], emoji="🖼️")

    async def log_name_change(
        self,
        mod: discord.Member,
        change_type: str,
        old_name: str,
        new_name: str,
    ) -> None:
        """Log a username or display name change."""
        embed = self._create_embed(
            title=f"{change_type} Changed",
            color=EmbedColors.WARNING,
            mod_avatar_url=mod.display_avatar.url,
        )
        self._add_mod_field(embed, mod)
        embed.add_field(name="Before", value=f"`{old_name}`", inline=True)
        embed.add_field(name="After", value=f"`{new_name}`", inline=True)

        if await self._send_log(mod.id, embed, f"{change_type} Change"):
            # Update stored info
            if change_type == "Username":
                self.db.update_mod_info(mod.id, username=new_name)
            elif change_type == "Display Name":
                self.db.update_mod_info(mod.id, display_name=new_name)

            logger.tree("Mod Tracker: Name Change Logged", [
                ("Mod", mod.display_name),
                ("Type", change_type),
                ("Before", old_name[:20]),
                ("After", new_name[:20]),
            ], emoji="✏️")

    async def log_message_delete(
        self,
        mod_id: int,
        channel: discord.TextChannel,
        content: str,
        attachments: List[discord.Attachment] = None,
        message_id: int = None,
        reply_to_user: discord.User = None,
        reply_to_id: int = None,
    ) -> None:
        """Log a deleted message with attachments."""
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return

        thread = await self._get_mod_thread(tracked["thread_id"])
        if not thread:
            return

        # Record action for bulk detection
        self._record_action(mod_id, "delete")

        # Build embed
        embed = self._create_embed(
            title="Message Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Attachments", value=str(len(attachments) if attachments else 0), inline=True)

        # Add reply info if this was a reply
        if reply_to_user and reply_to_id:
            embed.add_field(
                name="Reply To",
                value=f"{reply_to_user.mention}\n`{reply_to_user.name}` ({reply_to_id})",
                inline=True,
            )

        # Truncate content
        max_content_length = 1000
        if content:
            display_content = content[:max_content_length]
            if len(content) > max_content_length:
                display_content += "..."
            embed.add_field(name="Content", value=f"```{display_content}```", inline=False)
        else:
            embed.add_field(name="Content", value="*(No text content)*", inline=False)

        # Try to get attachments from cache first
        files_to_send: List[discord.File] = []
        cached_msg = self.get_cached_message(message_id) if message_id else None

        if cached_msg and cached_msg.attachments:
            # Use cached attachments
            for filename, data in cached_msg.attachments:
                file = discord.File(io.BytesIO(data), filename=filename)
                files_to_send.append(file)
        elif attachments:
            # Try to download from Discord (may fail if already deleted)
            async with aiohttp.ClientSession() as session:
                for attachment in attachments[:5]:
                    try:
                        if attachment.content_type and any(
                            t in attachment.content_type
                            for t in ["image", "video", "gif"]
                        ):
                            async with session.get(attachment.url) as resp:
                                if resp.status == 200:
                                    data = await resp.read()
                                    file = discord.File(
                                        io.BytesIO(data),
                                        filename=attachment.filename,
                                        spoiler=attachment.is_spoiler(),
                                    )
                                    files_to_send.append(file)
                    except Exception as e:
                        logger.debug(f"Mod Tracker: Failed to download attachment - {e}")

        try:
            if thread.archived:
                try:
                    await thread.edit(archived=False)
                    await asyncio.sleep(RATE_LIMIT_DELAY)
                except discord.HTTPException:
                    pass

            await thread.send(embed=embed, files=files_to_send if files_to_send else None)

            logger.tree("Mod Tracker: Message Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
                ("Attachments Saved", str(len(files_to_send))),
                ("From Cache", str(cached_msg is not None)),
            ], emoji="🗑️")

        except Exception as e:
            logger.error("Mod Tracker: Failed To Log Message Delete", [
                ("Mod ID", str(mod_id)),
                ("Error", str(e)[:50]),
            ])

        # Check for bulk action
        await self._check_bulk_action(mod_id, "delete")

    async def log_message_edit(
        self,
        mod: discord.Member,
        channel: discord.TextChannel,
        old_content: str,
        new_content: str,
        jump_url: str,
        reply_to_user: discord.User = None,
        reply_to_id: int = None,
    ) -> None:
        """Log an edited message."""
        embed = self._create_embed(
            title="Message Edited",
            color=EmbedColors.WARNING,
            mod_avatar_url=mod.display_avatar.url,
        )
        self._add_mod_field(embed, mod)
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Jump", value=f"[Go to message]({jump_url})", inline=True)

        # Add reply info if this was a reply
        if reply_to_user and reply_to_id:
            embed.add_field(
                name="Reply To",
                value=f"{reply_to_user.mention}\n`{reply_to_user.name}` ({reply_to_id})",
                inline=True,
            )

        # Truncate content
        max_content_length = 500
        old_display = old_content[:max_content_length]
        if len(old_content) > max_content_length:
            old_display += "..."
        new_display = new_content[:max_content_length]
        if len(new_content) > max_content_length:
            new_display += "..."

        embed.add_field(
            name="Before",
            value=f"```{old_display}```" if old_display else "*(empty)*",
            inline=False,
        )
        embed.add_field(
            name="After",
            value=f"```{new_display}```" if new_display else "*(empty)*",
            inline=False,
        )

        if await self._send_log(mod.id, embed, "Message Edit"):
            logger.tree("Mod Tracker: Message Edit Logged", [
                ("Mod", mod.display_name),
                ("Channel", channel.name),
            ], emoji="✏️")

    async def log_role_change(
        self,
        mod: discord.Member,
        added_roles: List[discord.Role],
        removed_roles: List[discord.Role],
    ) -> None:
        """Log role changes."""
        embed = self._create_embed(
            title="Roles Changed",
            color=EmbedColors.INFO,
            mod_avatar_url=mod.display_avatar.url,
        )
        self._add_mod_field(embed, mod)

        if added_roles:
            roles_str = ", ".join([r.name for r in added_roles])
            embed.add_field(name="Added", value=f"`{roles_str}`", inline=False)

        if removed_roles:
            roles_str = ", ".join([r.name for r in removed_roles])
            embed.add_field(name="Removed", value=f"`{roles_str}`", inline=False)

        if await self._send_log(mod.id, embed, "Role Change"):
            logger.tree("Mod Tracker: Role Change Logged", [
                ("Mod", mod.display_name),
                ("Added", str(len(added_roles))),
                ("Removed", str(len(removed_roles))),
            ], emoji="🎭")

    async def log_voice_activity(
        self,
        mod: discord.Member,
        action: str,
        channel: Optional[discord.VoiceChannel] = None,
        from_channel: Optional[discord.VoiceChannel] = None,
        to_channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        """Log voice channel activity."""
        embed = self._create_embed(
            title=f"Voice: {action}",
            color=EmbedColors.INFO,
            mod_avatar_url=mod.display_avatar.url,
        )
        self._add_mod_field(embed, mod)

        if channel:
            embed.add_field(name="Channel", value=f"{channel.name}", inline=True)
        if from_channel:
            embed.add_field(name="From", value=f"{from_channel.name}", inline=True)
        if to_channel:
            embed.add_field(name="To", value=f"{to_channel.name}", inline=True)

        if await self._send_log(mod.id, embed, f"Voice {action}"):
            logger.tree("Mod Tracker: Voice Activity Logged", [
                ("Mod", mod.display_name),
                ("Action", action),
            ], emoji="🎤")

    # =========================================================================
    # Activity Logging - Mute/Unmute Commands
    # =========================================================================

    async def log_mute(
        self,
        mod: discord.Member,
        target: discord.Member,
        duration: str,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod mutes a user via /mute command."""
        embed = self._create_embed(
            title="Muted User",
            color=EmbedColors.ERROR,
            mod_avatar_url=mod.display_avatar.url,
        )
        self._add_mod_field(embed, mod)

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)

        # Add target's avatar as image
        embed.set_image(url=target.display_avatar.url)

        if await self._send_log(mod.id, embed, "Mute"):
            logger.tree("Mod Tracker: Mute Logged", [
                ("Mod", mod.display_name),
                ("Target", target.display_name),
                ("Duration", duration),
            ], emoji="🔇")

    async def log_unmute(
        self,
        mod: discord.Member,
        target: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod unmutes a user via /unmute command."""
        embed = self._create_embed(
            title="Unmuted User",
            color=EmbedColors.SUCCESS,
            mod_avatar_url=mod.display_avatar.url,
        )
        self._add_mod_field(embed, mod)

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)

        # Add target's avatar as image
        embed.set_image(url=target.display_avatar.url)

        if await self._send_log(mod.id, embed, "Unmute"):
            logger.tree("Mod Tracker: Unmute Logged", [
                ("Mod", mod.display_name),
                ("Target", target.display_name),
            ], emoji="🔊")

    # =========================================================================
    # Mod Action Logging (Timeout/Kick/Ban)
    # =========================================================================

    async def log_timeout(
        self,
        mod_id: int,
        target: discord.Member,
        until: Optional[datetime] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod times out a member with dynamic countdown."""
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return

        # Record action
        self._record_action(mod_id, "timeout")

        # Try to get mod member for avatar
        mod_avatar_url = None
        try:
            guild = self.bot.get_guild(self.config.mod_server_id)
            if guild:
                mod_member = guild.get_member(mod_id)
                if mod_member:
                    mod_avatar_url = mod_member.display_avatar.url
        except Exception:
            pass

        embed = self._create_embed(
            title="⏰ Timeout",
            color=EmbedColors.WARNING,
            mod_avatar_url=mod_avatar_url,
        )

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )

        # Dynamic countdown that auto-updates
        if until:
            timestamp = int(until.timestamp())
            embed.add_field(
                name="Unmutes",
                value=f"<t:{timestamp}:R>",  # Relative (in 6 days)
                inline=True,
            )
            embed.add_field(
                name="Unmute Date",
                value=f"<t:{timestamp}:F>",  # Full date (December 28, 2025 2:09 PM)
                inline=True,
            )
        else:
            embed.add_field(name="Duration", value="Unknown", inline=True)

        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)

        if hasattr(target, 'display_avatar'):
            embed.set_image(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Timeout"):
            logger.tree("Mod Tracker: Timeout Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji="⏰")

        # Check for bulk action
        await self._check_bulk_action(mod_id, "timeout")

    async def log_kick(
        self,
        mod_id: int,
        target: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod kicks a member."""
        await self._log_mod_action(
            mod_id=mod_id,
            action="Kick",
            emoji_icon="👢",
            target=target,
            extra_fields=[
                ("Reason", reason or "No reason provided"),
            ],
        )

    async def log_ban(
        self,
        mod_id: int,
        target: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod bans a member."""
        # Record for suspicious pattern detection
        self._record_ban(mod_id, target.id)

        await self._log_mod_action(
            mod_id=mod_id,
            action="Ban",
            emoji_icon="🔨",
            target=target,
            extra_fields=[
                ("Reason", reason or "No reason provided"),
            ],
        )

    async def log_unban(
        self,
        mod_id: int,
        target: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod unbans a member."""
        # Check for suspicious pattern (unbanning someone they recently banned)
        await self._check_suspicious_unban(mod_id, target.id)

        await self._log_mod_action(
            mod_id=mod_id,
            action="Unban",
            emoji_icon="🔓",
            target=target,
            extra_fields=[
                ("Reason", reason or "No reason provided"),
            ],
        )

    async def _log_mod_action(
        self,
        mod_id: int,
        action: str,
        emoji_icon: str,
        target: discord.User,
        extra_fields: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        """Helper to log mod actions."""
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return

        # Record action for bulk detection and inactivity tracking
        action_type = action.lower()
        self._record_action(mod_id, action_type)

        # Try to get mod member for avatar
        mod_avatar_url = None
        try:
            guild = self.bot.get_guild(self.config.mod_server_id)
            if guild:
                mod_member = guild.get_member(mod_id)
                if mod_member:
                    mod_avatar_url = mod_member.display_avatar.url
        except Exception:
            pass

        embed = self._create_embed(
            title=f"{emoji_icon} {action}",
            color=EmbedColors.WARNING,
            mod_avatar_url=mod_avatar_url,
        )

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )

        if extra_fields:
            for name, value in extra_fields:
                embed.add_field(name=name, value=value, inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_image(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, action):
            logger.tree(f"Mod Tracker: {action} Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji=emoji_icon)

        # Check for bulk action
        await self._check_bulk_action(mod_id, action_type)

    # =========================================================================
    # Channel/Permission Logging
    # =========================================================================

    async def log_channel_create(
        self,
        mod_id: int,
        channel: discord.abc.GuildChannel,
    ) -> None:
        """Log when mod creates a channel."""
        await self._log_channel_action(mod_id, "Created", "📁", channel)

    async def log_channel_delete(
        self,
        mod_id: int,
        channel_name: str,
        channel_type: str,
    ) -> None:
        """Log when mod deletes a channel."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Channel Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=f"`{channel_name}`", inline=True)
        embed.add_field(name="Type", value=channel_type, inline=True)

        if await self._send_log(mod_id, embed, "Channel Delete"):
            logger.tree("Mod Tracker: Channel Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel_name),
            ], emoji="🗑️")

    async def log_channel_update(
        self,
        mod_id: int,
        channel: discord.abc.GuildChannel,
        changes: str,
    ) -> None:
        """Log when mod updates a channel."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Channel Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)

        max_changes_length = 1000
        embed.add_field(
            name="Changes",
            value=changes[:max_changes_length],
            inline=False,
        )

        if await self._send_log(mod_id, embed, "Channel Update"):
            logger.tree("Mod Tracker: Channel Update Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
            ], emoji="✏️")

    async def _log_channel_action(
        self,
        mod_id: int,
        action: str,
        emoji_icon: str,
        channel: discord.abc.GuildChannel,
    ) -> None:
        """Helper to log channel actions."""
        if not self.enabled:
            return

        channel_type = type(channel).__name__.replace("Channel", "")

        embed = self._create_embed(
            title=f"{emoji_icon} Channel {action}",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Type", value=channel_type, inline=True)
        embed.add_field(name="ID", value=f"`{channel.id}`", inline=True)

        if await self._send_log(mod_id, embed, f"Channel {action}"):
            logger.tree(f"Mod Tracker: Channel {action} Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
            ], emoji=emoji_icon)

    # =========================================================================
    # Role Logging
    # =========================================================================

    async def log_role_create(
        self,
        mod_id: int,
        role: discord.Role,
    ) -> None:
        """Log when mod creates a role."""
        await self._log_role_action(mod_id, "Created", "🏷️", role)

    async def log_role_delete(
        self,
        mod_id: int,
        role_name: str,
    ) -> None:
        """Log when mod deletes a role."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Role Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=f"`{role_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Role Delete"):
            logger.tree("Mod Tracker: Role Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Role", role_name),
            ], emoji="🗑️")

    async def log_role_update(
        self,
        mod_id: int,
        role: discord.Role,
        changes: str,
    ) -> None:
        """Log when mod updates a role."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Role Updated",
            color=role.color if role.color.value else EmbedColors.WARNING,
        )
        embed.add_field(name="Role", value=f"`{role.name}`", inline=True)

        max_changes_length = 1000
        embed.add_field(name="Changes", value=changes[:max_changes_length], inline=False)

        if await self._send_log(mod_id, embed, "Role Update"):
            logger.tree("Mod Tracker: Role Update Logged", [
                ("Mod ID", str(mod_id)),
                ("Role", role.name),
            ], emoji="✏️")

    async def _log_role_action(
        self,
        mod_id: int,
        action: str,
        emoji_icon: str,
        role: discord.Role,
    ) -> None:
        """Helper to log role actions."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title=f"{emoji_icon} Role {action}",
            color=role.color if role.color.value else EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=f"`{role.name}`", inline=True)
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)

        if await self._send_log(mod_id, embed, f"Role {action}"):
            logger.tree(f"Mod Tracker: Role {action} Logged", [
                ("Mod ID", str(mod_id)),
                ("Role", role.name),
            ], emoji=emoji_icon)

    # =========================================================================
    # Message Pin/Reaction Logging
    # =========================================================================

    async def log_message_pin(
        self,
        mod_id: int,
        channel: discord.TextChannel,
        message: discord.Message,
        pinned: bool,
    ) -> None:
        """Log when mod pins/unpins a message."""
        if not self.enabled:
            return

        action = "Pinned" if pinned else "Unpinned"
        emoji_icon = "📌" if pinned else "📍"

        embed = self._create_embed(
            title=f"{emoji_icon} Message {action}",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Author", value=f"{message.author}", inline=True)
        embed.add_field(name="Link", value=f"[Jump]({message.jump_url})", inline=True)

        if message.content:
            max_content_length = 200
            content = message.content[:max_content_length]
            if len(message.content) > max_content_length:
                content += "..."
            embed.add_field(name="Content", value=f"```{content}```", inline=False)

        if await self._send_log(mod_id, embed, f"Message {action}"):
            logger.tree(f"Mod Tracker: Message {action} Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
            ], emoji=emoji_icon)

    # =========================================================================
    # Thread Logging
    # =========================================================================

    async def log_thread_create(
        self,
        mod_id: int,
        thread: discord.Thread,
    ) -> None:
        """Log when mod creates a thread."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Thread Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=thread.name, inline=True)

        parent_name = "Unknown"
        if thread.parent:
            parent_name = thread.parent.name
        embed.add_field(name="Parent", value=f"#{parent_name}", inline=True)
        embed.add_field(name="Link", value=f"[Jump]({thread.jump_url})", inline=True)

        if await self._send_log(mod_id, embed, "Thread Create"):
            logger.tree("Mod Tracker: Thread Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Thread", thread.name),
            ], emoji="🧵")

    async def log_thread_delete(
        self,
        mod_id: int,
        thread_name: str,
        parent_name: str,
    ) -> None:
        """Log when mod deletes a thread."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Thread Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=thread_name, inline=True)
        embed.add_field(name="Parent", value=f"#{parent_name}", inline=True)

        if await self._send_log(mod_id, embed, "Thread Delete"):
            logger.tree("Mod Tracker: Thread Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Thread", thread_name),
            ], emoji="🗑️")

    # =========================================================================
    # Invite Logging
    # =========================================================================

    async def log_invite_create(
        self,
        mod_id: int,
        invite: discord.Invite,
    ) -> None:
        """Log when mod creates an invite."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Invite Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Code", value=f"`{invite.code}`", inline=True)

        channel_name = "Unknown"
        if invite.channel:
            channel_name = invite.channel.name
        embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)

        max_uses = "Unlimited"
        if invite.max_uses:
            max_uses = str(invite.max_uses)
        embed.add_field(name="Max Uses", value=max_uses, inline=True)

        # Handle expiry safely
        expiry_display = "Never"
        if invite.max_age and invite.max_age > 0:
            expiry_time = datetime.now(NY_TZ) + timedelta(seconds=invite.max_age)
            expiry_display = f"<t:{int(expiry_time.timestamp())}:R>"
        embed.add_field(name="Expires", value=expiry_display, inline=True)

        if await self._send_log(mod_id, embed, "Invite Create"):
            logger.tree("Mod Tracker: Invite Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Code", invite.code),
            ], emoji="🔗")

    async def log_invite_delete(
        self,
        mod_id: int,
        invite_code: str,
        channel_name: str,
    ) -> None:
        """Log when mod deletes an invite."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Invite Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Code", value=f"`{invite_code}`", inline=True)
        embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)

        if await self._send_log(mod_id, embed, "Invite Delete"):
            logger.tree("Mod Tracker: Invite Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Code", invite_code),
            ], emoji="🗑️")

    # =========================================================================
    # Emoji/Sticker Logging
    # =========================================================================

    async def log_emoji_create(
        self,
        mod_id: int,
        emoji: discord.Emoji,
    ) -> None:
        """Log when mod creates an emoji."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Emoji Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=f"`:{emoji.name}:`", inline=True)
        embed.add_field(name="ID", value=f"`{emoji.id}`", inline=True)
        embed.set_image(url=emoji.url)

        if await self._send_log(mod_id, embed, "Emoji Create"):
            logger.tree("Mod Tracker: Emoji Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Emoji", emoji.name),
            ], emoji="😀")

    async def log_emoji_delete(
        self,
        mod_id: int,
        emoji_name: str,
    ) -> None:
        """Log when mod deletes an emoji."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Emoji Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=f"`:{emoji_name}:`", inline=True)

        if await self._send_log(mod_id, embed, "Emoji Delete"):
            logger.tree("Mod Tracker: Emoji Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Emoji", emoji_name),
            ], emoji="🗑️")

    async def log_sticker_create(
        self,
        mod_id: int,
        sticker: discord.GuildSticker,
    ) -> None:
        """Log when mod creates a sticker."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Sticker Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=sticker.name, inline=True)
        embed.add_field(name="ID", value=f"`{sticker.id}`", inline=True)
        embed.set_image(url=sticker.url)

        if await self._send_log(mod_id, embed, "Sticker Create"):
            logger.tree("Mod Tracker: Sticker Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Sticker", sticker.name),
            ], emoji="🎨")

    async def log_sticker_delete(
        self,
        mod_id: int,
        sticker_name: str,
    ) -> None:
        """Log when mod deletes a sticker."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Sticker Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=sticker_name, inline=True)

        if await self._send_log(mod_id, embed, "Sticker Delete"):
            logger.tree("Mod Tracker: Sticker Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Sticker", sticker_name),
            ], emoji="🗑️")

    # =========================================================================
    # Webhook Logging
    # =========================================================================

    async def log_webhook_create(
        self,
        mod_id: int,
        webhook_name: str,
        channel_name: str,
    ) -> None:
        """Log when mod creates a webhook."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Webhook Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=webhook_name, inline=True)
        embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)

        if await self._send_log(mod_id, embed, "Webhook Create"):
            logger.tree("Mod Tracker: Webhook Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Webhook", webhook_name),
            ], emoji="🔌")

    async def log_webhook_delete(
        self,
        mod_id: int,
        webhook_name: str,
        channel_name: str,
    ) -> None:
        """Log when mod deletes a webhook."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Webhook Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=webhook_name, inline=True)
        embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)

        if await self._send_log(mod_id, embed, "Webhook Delete"):
            logger.tree("Mod Tracker: Webhook Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Webhook", webhook_name),
            ], emoji="🗑️")

    # =========================================================================
    # Server Settings Logging
    # =========================================================================

    async def log_guild_update(
        self,
        mod_id: int,
        changes: str,
    ) -> None:
        """Log when mod changes server settings."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="Server Settings Changed",
            color=EmbedColors.WARNING,
        )

        max_changes_length = 1000
        embed.add_field(name="Changes", value=changes[:max_changes_length], inline=False)

        if await self._send_log(mod_id, embed, "Guild Update"):
            logger.tree("Mod Tracker: Guild Update Logged", [
                ("Mod ID", str(mod_id)),
            ], emoji="⚙️")

    # =========================================================================
    # Slowmode Logging
    # =========================================================================

    async def log_slowmode_change(
        self,
        mod_id: int,
        channel: discord.TextChannel,
        old_delay: int,
        new_delay: int,
    ) -> None:
        """Log when mod changes channel slowmode."""
        if not self.enabled:
            return

        # Record action
        self._record_action(mod_id, "slowmode")

        embed = self._create_embed(
            title="Slowmode Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)

        if old_delay == 0:
            old_text = "Off"
        elif old_delay < 60:
            old_text = f"{old_delay}s"
        elif old_delay < 3600:
            old_text = f"{old_delay // 60}m"
        else:
            old_text = f"{old_delay // 3600}h"

        if new_delay == 0:
            new_text = "Off"
        elif new_delay < 60:
            new_text = f"{new_delay}s"
        elif new_delay < 3600:
            new_text = f"{new_delay // 60}m"
        else:
            new_text = f"{new_delay // 3600}h"

        embed.add_field(name="Before", value=old_text, inline=True)
        embed.add_field(name="After", value=new_text, inline=True)

        if await self._send_log(mod_id, embed, "Slowmode Change"):
            logger.tree("Mod Tracker: Slowmode Change Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
                ("New Delay", new_text),
            ], emoji="🐌")

    # =========================================================================
    # AutoMod Logging
    # =========================================================================

    async def log_automod_rule_create(
        self,
        mod_id: int,
        rule_name: str,
        trigger_type: str,
    ) -> None:
        """Log when mod creates an automod rule."""
        if not self.enabled:
            return

        self._record_action(mod_id, "automod")

        embed = self._create_embed(
            title="AutoMod Rule Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Rule Name", value=rule_name, inline=True)
        embed.add_field(name="Trigger", value=trigger_type, inline=True)

        if await self._send_log(mod_id, embed, "AutoMod Create"):
            logger.tree("Mod Tracker: AutoMod Rule Created", [
                ("Mod ID", str(mod_id)),
                ("Rule", rule_name),
            ], emoji="🤖")

    async def log_automod_rule_update(
        self,
        mod_id: int,
        rule_name: str,
        changes: str,
    ) -> None:
        """Log when mod updates an automod rule."""
        if not self.enabled:
            return

        self._record_action(mod_id, "automod")

        embed = self._create_embed(
            title="AutoMod Rule Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Rule Name", value=rule_name, inline=True)
        embed.add_field(name="Changes", value=changes[:500], inline=False)

        if await self._send_log(mod_id, embed, "AutoMod Update"):
            logger.tree("Mod Tracker: AutoMod Rule Updated", [
                ("Mod ID", str(mod_id)),
                ("Rule", rule_name),
            ], emoji="🤖")

    async def log_automod_rule_delete(
        self,
        mod_id: int,
        rule_name: str,
    ) -> None:
        """Log when mod deletes an automod rule."""
        if not self.enabled:
            return

        self._record_action(mod_id, "automod")

        embed = self._create_embed(
            title="AutoMod Rule Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Rule Name", value=rule_name, inline=True)

        if await self._send_log(mod_id, embed, "AutoMod Delete"):
            logger.tree("Mod Tracker: AutoMod Rule Deleted", [
                ("Mod ID", str(mod_id)),
                ("Rule", rule_name),
            ], emoji="🗑️")

    # =========================================================================
    # User Nickname Change Logging
    # =========================================================================

    async def log_nickname_change(
        self,
        mod_id: int,
        target: discord.Member,
        old_nick: Optional[str],
        new_nick: Optional[str],
    ) -> None:
        """Log when mod changes another user's nickname."""
        if not self.enabled:
            return

        self._record_action(mod_id, "nickname")

        embed = self._create_embed(
            title="Nickname Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )
        embed.add_field(name="Before", value=old_nick or "*(none)*", inline=True)
        embed.add_field(name="After", value=new_nick or "*(none)*", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Nickname Change"):
            logger.tree("Mod Tracker: Nickname Change Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji="✏️")

    # =========================================================================
    # Voice Channel Move Logging
    # =========================================================================

    async def log_voice_move(
        self,
        mod_id: int,
        target: discord.Member,
        from_channel: discord.VoiceChannel,
        to_channel: discord.VoiceChannel,
    ) -> None:
        """Log when mod moves a user between voice channels."""
        if not self.enabled:
            return

        self._record_action(mod_id, "voice_move")

        embed = self._create_embed(
            title="User Moved (Voice)",
            color=EmbedColors.WARNING,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )
        embed.add_field(name="From", value=f"🔊 {from_channel.name}", inline=True)
        embed.add_field(name="To", value=f"🔊 {to_channel.name}", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Voice Move"):
            logger.tree("Mod Tracker: Voice Move Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
                ("To", to_channel.name),
            ], emoji="🔊")

    # =========================================================================
    # Bulk Message Purge Logging
    # =========================================================================

    async def log_message_purge(
        self,
        mod_id: int,
        channel: discord.TextChannel,
        count: int,
    ) -> None:
        """Log when mod purges/bulk deletes messages."""
        if not self.enabled:
            return

        self._record_action(mod_id, "purge")

        embed = self._create_embed(
            title="Messages Purged",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Count", value=f"**{count}** messages", inline=True)

        if await self._send_log(mod_id, embed, "Message Purge"):
            logger.tree("Mod Tracker: Message Purge Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
                ("Count", str(count)),
            ], emoji="🧹")

    # =========================================================================
    # User Role Change Logging
    # =========================================================================

    async def log_role_assign(
        self,
        mod_id: int,
        target: discord.Member,
        role: discord.Role,
        action: str,  # "added" or "removed"
    ) -> None:
        """Log when mod adds/removes a role from a user."""
        if not self.enabled:
            return

        self._record_action(mod_id, "role_assign")

        if action == "added":
            title = "Role Added to User"
            color = EmbedColors.INFO
            emoji = "➕"
        else:
            title = "Role Removed from User"
            color = EmbedColors.ERROR
            emoji = "➖"

        embed = self._create_embed(
            title=title,
            color=color,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )
        embed.add_field(name="Role", value=f"{role.mention} (`{role.name}`)", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, f"Role {action.title()}"):
            logger.tree(f"Mod Tracker: Role {action.title()} Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
                ("Role", role.name),
            ], emoji=emoji)

    # =========================================================================
    # Voice Moderation Logging
    # =========================================================================

    async def log_voice_mute_deafen(
        self,
        mod_id: int,
        target: discord.Member,
        action: str,  # "muted", "unmuted", "deafened", "undeafened"
    ) -> None:
        """Log when mod server mutes/deafens a user."""
        if not self.enabled:
            return

        self._record_action(mod_id, "voice_mod")

        emoji_map = {
            "muted": "🔇",
            "unmuted": "🔊",
            "deafened": "🔇",
            "undeafened": "🔊",
        }
        color = EmbedColors.ERROR if action in ["muted", "deafened"] else EmbedColors.SUCCESS

        embed = self._create_embed(
            title=f"User {action.title()} (Voice)",
            color=color,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, f"Voice {action.title()}"):
            logger.tree(f"Mod Tracker: Voice {action.title()} Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji=emoji_map.get(action, "🔊"))

    async def log_voice_disconnect(
        self,
        mod_id: int,
        target: discord.Member,
        channel_name: str,
    ) -> None:
        """Log when mod disconnects a user from voice."""
        if not self.enabled:
            return

        self._record_action(mod_id, "voice_disconnect")

        embed = self._create_embed(
            title="User Disconnected (Voice)",
            color=EmbedColors.ERROR,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )
        embed.add_field(name="From Channel", value=f"🔊 {channel_name}", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Voice Disconnect"):
            logger.tree("Mod Tracker: Voice Disconnect Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji="🔌")

    # =========================================================================
    # Channel Permission Overwrite Logging
    # =========================================================================

    async def log_permission_overwrite(
        self,
        mod_id: int,
        channel: discord.abc.GuildChannel,
        target: str,  # Role or user name
        target_type: str,  # "role" or "member"
        action: str,  # "added", "updated", "removed"
    ) -> None:
        """Log when mod changes channel permission overwrites."""
        if not self.enabled:
            return

        self._record_action(mod_id, "permission")

        # Track for mass permission change detection
        self._record_permission_change(mod_id)

        color_map = {
            "added": EmbedColors.INFO,
            "updated": EmbedColors.WARNING,
            "removed": EmbedColors.ERROR,
        }

        embed = self._create_embed(
            title=f"Permission Overwrite {action.title()}",
            color=color_map.get(action, EmbedColors.WARNING),
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Target", value=target, inline=True)
        embed.add_field(name="Type", value=target_type.title(), inline=True)

        if await self._send_log(mod_id, embed, f"Permission {action.title()}"):
            logger.tree(f"Mod Tracker: Permission {action.title()} Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
                ("Target", target),
            ], emoji="🔐")

        # Check for mass permission changes
        await self._check_mass_permission_change(mod_id)

    # =========================================================================
    # Sticker Logging
    # =========================================================================

    async def log_sticker_create(
        self,
        mod_id: int,
        sticker_name: str,
    ) -> None:
        """Log when mod creates a sticker."""
        if not self.enabled:
            return

        self._record_action(mod_id, "sticker")

        embed = self._create_embed(
            title="Sticker Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=sticker_name, inline=True)

        if await self._send_log(mod_id, embed, "Sticker Create"):
            logger.tree("Mod Tracker: Sticker Created", [
                ("Mod ID", str(mod_id)),
                ("Sticker", sticker_name),
            ], emoji="🎨")

    async def log_sticker_delete(
        self,
        mod_id: int,
        sticker_name: str,
    ) -> None:
        """Log when mod deletes a sticker."""
        if not self.enabled:
            return

        self._record_action(mod_id, "sticker")

        embed = self._create_embed(
            title="Sticker Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=sticker_name, inline=True)

        if await self._send_log(mod_id, embed, "Sticker Delete"):
            logger.tree("Mod Tracker: Sticker Deleted", [
                ("Mod ID", str(mod_id)),
                ("Sticker", sticker_name),
            ], emoji="🗑️")

    # =========================================================================
    # Scheduled Event Logging
    # =========================================================================

    async def log_event_create(
        self,
        mod_id: int,
        event_name: str,
        event_type: str,
    ) -> None:
        """Log when mod creates a scheduled event."""
        if not self.enabled:
            return

        self._record_action(mod_id, "event")

        embed = self._create_embed(
            title="Scheduled Event Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=event_name, inline=True)
        embed.add_field(name="Type", value=event_type, inline=True)

        if await self._send_log(mod_id, embed, "Event Create"):
            logger.tree("Mod Tracker: Event Created", [
                ("Mod ID", str(mod_id)),
                ("Event", event_name),
            ], emoji="📅")

    async def log_event_update(
        self,
        mod_id: int,
        event_name: str,
    ) -> None:
        """Log when mod updates a scheduled event."""
        if not self.enabled:
            return

        self._record_action(mod_id, "event")

        embed = self._create_embed(
            title="Scheduled Event Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Name", value=event_name, inline=True)

        if await self._send_log(mod_id, embed, "Event Update"):
            logger.tree("Mod Tracker: Event Updated", [
                ("Mod ID", str(mod_id)),
                ("Event", event_name),
            ], emoji="📅")

    async def log_event_delete(
        self,
        mod_id: int,
        event_name: str,
    ) -> None:
        """Log when mod deletes a scheduled event."""
        if not self.enabled:
            return

        self._record_action(mod_id, "event")

        embed = self._create_embed(
            title="Scheduled Event Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=event_name, inline=True)

        if await self._send_log(mod_id, embed, "Event Delete"):
            logger.tree("Mod Tracker: Event Deleted", [
                ("Mod ID", str(mod_id)),
                ("Event", event_name),
            ], emoji="🗑️")

    # =========================================================================
    # Command Usage Logging
    # =========================================================================

    async def log_command_usage(
        self,
        mod_id: int,
        command_name: str,
        target: Optional[discord.User] = None,
        extra_info: Optional[str] = None,
    ) -> None:
        """Log when mod uses a bot command."""
        if not self.enabled:
            return

        self._record_action(mod_id, "command")

        embed = self._create_embed(
            title="Command Used",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Command", value=f"`/{command_name}`", inline=True)

        if target:
            embed.add_field(
                name="Target",
                value=f"{target.mention}\n`{target.name}` ({target.id})",
                inline=True,
            )

        if extra_info:
            embed.add_field(name="Details", value=extra_info, inline=False)

        if await self._send_log(mod_id, embed, "Command Usage"):
            logger.debug(f"Mod Tracker: Command Usage Logged - {mod_id} used /{command_name}")

    # =========================================================================
    # Mod Notes
    # =========================================================================

    async def add_mod_note(
        self,
        mod_id: int,
        note: str,
        added_by: discord.User,
    ) -> bool:
        """Add a note to a mod's tracking thread."""
        if not self.enabled:
            return False

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return False

        thread = await self._get_mod_thread(tracked["thread_id"])
        if not thread:
            return False

        embed = self._create_embed(
            title="📝 Mod Note Added",
            color=0x808080,  # Gray
        )
        embed.add_field(name="Note", value=note, inline=False)
        embed.add_field(name="Added By", value=f"{added_by.mention} ({added_by.id})", inline=True)

        try:
            if thread.archived:
                await thread.edit(archived=False)
                await asyncio.sleep(RATE_LIMIT_DELAY)

            await thread.send(embed=embed)

            logger.tree("Mod Tracker: Note Added", [
                ("Mod ID", str(mod_id)),
                ("By", str(added_by)),
            ], emoji="📝")

            return True
        except Exception as e:
            logger.error("Mod Tracker: Failed To Add Note", [
                ("Mod ID", str(mod_id)),
                ("Error", str(e)[:50]),
            ])
            return False

    # =========================================================================
    # Security Alerts
    # =========================================================================

    async def alert_dm_attempt(
        self,
        mod_id: int,
        message_content: str,
    ) -> None:
        """Alert when tracked mod DMs the bot."""
        if not self.enabled:
            return

        await self._send_alert(
            mod_id=mod_id,
            alert_type="DM Attempt",
            description=f"Mod attempted to DM the bot.\n\n**Message:**\n```{message_content[:500]}```",
            color=EmbedColors.WARNING,
        )

        logger.tree("Mod Tracker: DM Attempt Alert", [
            ("Mod ID", str(mod_id)),
        ], emoji="⚠️")

    async def alert_self_role_change(
        self,
        mod_id: int,
        role: discord.Role,
        action: str,  # "added" or "removed"
    ) -> None:
        """Alert when mod changes their own roles (potential self-elevation)."""
        if not self.enabled:
            return

        description = f"Mod {action} a role to/from themselves.\n\n**Role:** {role.mention} (`{role.name}`)"

        if role.permissions.administrator or role.permissions.manage_guild:
            description += "\n\n**⚠️ This role has elevated permissions!**"

        await self._send_alert(
            mod_id=mod_id,
            alert_type="Self Role Change",
            description=description,
            color=EmbedColors.ERROR,
        )

        logger.tree("Mod Tracker: Self Role Change Alert", [
            ("Mod ID", str(mod_id)),
            ("Role", role.name),
            ("Action", action),
        ], emoji="🚨")

    # =========================================================================
    # Suspicious Pattern Detection
    # =========================================================================

    def _record_ban(self, mod_id: int, target_id: int) -> None:
        """Record a ban for suspicious pattern detection."""
        now = datetime.now(NY_TZ)
        self._ban_history[mod_id][target_id] = now

        # Clean old entries
        cutoff = now - timedelta(seconds=BAN_HISTORY_TTL)
        self._ban_history[mod_id] = {
            tid: t for tid, t in self._ban_history[mod_id].items()
            if t > cutoff
        }

    async def _check_suspicious_unban(self, mod_id: int, target_id: int) -> None:
        """Check if this unban is suspicious (unbanning someone they recently banned)."""
        if target_id not in self._ban_history[mod_id]:
            return

        ban_time = self._ban_history[mod_id][target_id]
        now = datetime.now(NY_TZ)
        time_since_ban = (now - ban_time).total_seconds()

        if time_since_ban <= SUSPICIOUS_UNBAN_WINDOW:
            minutes = int(time_since_ban / 60)
            await self._send_alert(
                mod_id=mod_id,
                alert_type="Suspicious Unban Pattern",
                description=f"Mod unbanned a user they banned **{minutes} minutes ago**.\n\n"
                           f"**Target ID:** `{target_id}`\n"
                           f"**Banned at:** <t:{int(ban_time.timestamp())}:R>\n\n"
                           f"This could indicate:\n"
                           f"• Accidental ban/unban\n"
                           f"• Pressure to unban\n"
                           f"• Abuse of mod powers",
                color=EmbedColors.ERROR,
            )

            # Remove from history after alerting
            del self._ban_history[mod_id][target_id]

            logger.tree("Mod Tracker: Suspicious Unban Alert", [
                ("Mod ID", str(mod_id)),
                ("Target ID", str(target_id)),
                ("Minutes Since Ban", str(minutes)),
            ], emoji="🚨")

    # =========================================================================
    # Mass Permission Change Detection
    # =========================================================================

    def _record_permission_change(self, mod_id: int) -> None:
        """Record a permission change for mass detection."""
        now = datetime.now(NY_TZ)
        self._permission_changes[mod_id].append(now)

        # Clean old entries
        cutoff = now - timedelta(seconds=MASS_PERMISSION_WINDOW)
        self._permission_changes[mod_id] = [
            t for t in self._permission_changes[mod_id] if t > cutoff
        ]

    async def _check_mass_permission_change(self, mod_id: int) -> None:
        """Check if mod is making mass permission changes."""
        count = len(self._permission_changes[mod_id])

        if count >= MASS_PERMISSION_THRESHOLD:
            await self._send_alert(
                mod_id=mod_id,
                alert_type="Mass Permission Changes",
                description=f"Mod changed permissions on **{count}** channels in the last 5 minutes.\n\n"
                           f"This could indicate:\n"
                           f"• Server restructuring\n"
                           f"• Potential lockdown attempt\n"
                           f"• Permission abuse",
                color=EmbedColors.ERROR,
            )

            # Clear after alerting to avoid spam
            self._permission_changes[mod_id].clear()

            logger.tree("Mod Tracker: Mass Permission Alert", [
                ("Mod ID", str(mod_id)),
                ("Count", str(count)),
            ], emoji="🚨")

    # =========================================================================
    # Stage Channel Moderation
    # =========================================================================

    async def log_stage_speaker(
        self,
        mod_id: int,
        target: discord.Member,
        stage_channel: discord.StageChannel,
        action: str,  # "added" or "removed"
    ) -> None:
        """Log when mod adds/removes a stage speaker."""
        if not self.enabled:
            return

        self._record_action(mod_id, "stage")

        if action == "added":
            title = "Stage Speaker Added"
            color = EmbedColors.SUCCESS
        else:
            title = "Stage Speaker Removed"
            color = EmbedColors.ERROR

        embed = self._create_embed(title=title, color=color)
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )
        embed.add_field(name="Stage", value=f"🎭 {stage_channel.name}", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, f"Stage Speaker {action.title()}"):
            logger.tree(f"Mod Tracker: Stage Speaker {action.title()}", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
                ("Stage", stage_channel.name),
            ], emoji="🎭")

    async def log_stage_topic_change(
        self,
        mod_id: int,
        stage_channel: discord.StageChannel,
        old_topic: Optional[str],
        new_topic: Optional[str],
    ) -> None:
        """Log when mod changes stage topic."""
        if not self.enabled:
            return

        self._record_action(mod_id, "stage")

        embed = self._create_embed(
            title="Stage Topic Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Stage", value=f"🎭 {stage_channel.name}", inline=True)
        embed.add_field(name="Before", value=old_topic or "*(none)*", inline=False)
        embed.add_field(name="After", value=new_topic or "*(none)*", inline=False)

        if await self._send_log(mod_id, embed, "Stage Topic Change"):
            logger.tree("Mod Tracker: Stage Topic Changed", [
                ("Mod ID", str(mod_id)),
                ("Stage", stage_channel.name),
            ], emoji="🎭")

    # =========================================================================
    # Forum Tag Changes
    # =========================================================================

    async def log_forum_tag_create(
        self,
        mod_id: int,
        forum: discord.ForumChannel,
        tag_name: str,
    ) -> None:
        """Log when mod creates a forum tag."""
        if not self.enabled:
            return

        self._record_action(mod_id, "forum_tag")

        embed = self._create_embed(
            title="Forum Tag Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Forum", value=f"#{forum.name}", inline=True)
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Forum Tag Create"):
            logger.tree("Mod Tracker: Forum Tag Created", [
                ("Mod ID", str(mod_id)),
                ("Forum", forum.name),
                ("Tag", tag_name),
            ], emoji="🏷️")

    async def log_forum_tag_delete(
        self,
        mod_id: int,
        forum: discord.ForumChannel,
        tag_name: str,
    ) -> None:
        """Log when mod deletes a forum tag."""
        if not self.enabled:
            return

        self._record_action(mod_id, "forum_tag")

        embed = self._create_embed(
            title="Forum Tag Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Forum", value=f"#{forum.name}", inline=True)
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Forum Tag Delete"):
            logger.tree("Mod Tracker: Forum Tag Deleted", [
                ("Mod ID", str(mod_id)),
                ("Forum", forum.name),
                ("Tag", tag_name),
            ], emoji="🗑️")

    async def log_forum_tag_update(
        self,
        mod_id: int,
        forum: discord.ForumChannel,
        old_name: str,
        new_name: str,
    ) -> None:
        """Log when mod updates a forum tag."""
        if not self.enabled:
            return

        self._record_action(mod_id, "forum_tag")

        embed = self._create_embed(
            title="Forum Tag Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Forum", value=f"#{forum.name}", inline=True)
        embed.add_field(name="Before", value=f"`{old_name}`", inline=True)
        embed.add_field(name="After", value=f"`{new_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Forum Tag Update"):
            logger.tree("Mod Tracker: Forum Tag Updated", [
                ("Mod ID", str(mod_id)),
                ("Forum", forum.name),
            ], emoji="✏️")

    # =========================================================================
    # Integration/Bot Tracking
    # =========================================================================

    async def log_integration_create(
        self,
        mod_id: int,
        integration_name: str,
        integration_type: str,
    ) -> None:
        """Log when mod adds an integration/bot."""
        if not self.enabled:
            return

        self._record_action(mod_id, "integration")

        embed = self._create_embed(
            title="Integration Added",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=integration_name, inline=True)
        embed.add_field(name="Type", value=integration_type, inline=True)

        if await self._send_log(mod_id, embed, "Integration Create"):
            logger.tree("Mod Tracker: Integration Added", [
                ("Mod ID", str(mod_id)),
                ("Integration", integration_name),
            ], emoji="🤖")

    async def log_integration_delete(
        self,
        mod_id: int,
        integration_name: str,
    ) -> None:
        """Log when mod removes an integration/bot."""
        if not self.enabled:
            return

        self._record_action(mod_id, "integration")

        embed = self._create_embed(
            title="Integration Removed",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=integration_name, inline=True)

        if await self._send_log(mod_id, embed, "Integration Delete"):
            logger.tree("Mod Tracker: Integration Removed", [
                ("Mod ID", str(mod_id)),
                ("Integration", integration_name),
            ], emoji="🗑️")

    async def log_bot_add(
        self,
        mod_id: int,
        bot: discord.Member,
    ) -> None:
        """Log when mod adds a bot to the server."""
        if not self.enabled:
            return

        self._record_action(mod_id, "bot")

        embed = self._create_embed(
            title="Bot Added",
            color=EmbedColors.WARNING,
        )
        embed.add_field(
            name="Bot",
            value=f"{bot.mention}\n`{bot.name}` ({bot.id})",
            inline=True,
        )

        if bot.avatar:
            embed.set_thumbnail(url=bot.display_avatar.url)

        if await self._send_log(mod_id, embed, "Bot Add"):
            logger.tree("Mod Tracker: Bot Added", [
                ("Mod ID", str(mod_id)),
                ("Bot", str(bot)),
                ("Bot ID", str(bot.id)),
            ], emoji="🤖")

    async def log_bot_remove(
        self,
        mod_id: int,
        bot_name: str,
        bot_id: int,
    ) -> None:
        """Log when mod removes a bot from the server."""
        if not self.enabled:
            return

        self._record_action(mod_id, "bot")

        embed = self._create_embed(
            title="Bot Removed",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Bot", value=f"`{bot_name}` ({bot_id})", inline=True)

        if await self._send_log(mod_id, embed, "Bot Remove"):
            logger.tree("Mod Tracker: Bot Removed", [
                ("Mod ID", str(mod_id)),
                ("Bot", bot_name),
                ("Bot ID", str(bot_id)),
            ], emoji="🗑️")

    # =========================================================================
    # Timeout Removal Tracking
    # =========================================================================

    async def log_timeout_remove(
        self,
        mod_id: int,
        target: discord.Member,
        original_until: Optional[datetime] = None,
    ) -> None:
        """Log when mod removes a timeout early."""
        if not self.enabled:
            return

        self._record_action(mod_id, "timeout_remove")

        embed = self._create_embed(
            title="Timeout Removed Early",
            color=EmbedColors.WARNING,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )

        if original_until:
            embed.add_field(
                name="Was Until",
                value=f"<t:{int(original_until.timestamp())}:R>",
                inline=True,
            )

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Timeout Remove"):
            logger.tree("Mod Tracker: Timeout Removed", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji="⏰")

    # =========================================================================
    # Prune Tracking
    # =========================================================================

    async def log_member_prune(
        self,
        mod_id: int,
        days: int,
        members_removed: int,
    ) -> None:
        """Log when mod prunes inactive members."""
        if not self.enabled:
            return

        self._record_action(mod_id, "prune")

        embed = self._create_embed(
            title="Member Prune",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Inactive Days", value=f"{days} days", inline=True)
        embed.add_field(name="Members Removed", value=f"**{members_removed}**", inline=True)

        # Alert about large prunes
        if members_removed >= 50:
            embed.add_field(
                name="⚠️ Warning",
                value="Large prune operation detected!",
                inline=False,
            )

        if await self._send_log(mod_id, embed, "Member Prune"):
            logger.tree("Mod Tracker: Member Prune", [
                ("Mod ID", str(mod_id)),
                ("Days", str(days)),
                ("Removed", str(members_removed)),
            ], emoji="🧹")

        # Alert for large prunes
        if members_removed >= 50:
            await self._send_alert(
                mod_id=mod_id,
                alert_type="Large Member Prune",
                description=f"Mod pruned **{members_removed}** members (inactive for {days}+ days).\n\n"
                           f"This is a significant action that removed many members.",
                color=EmbedColors.ERROR,
            )

    # =========================================================================
    # Server Settings Tracking
    # =========================================================================

    async def log_verification_level_change(
        self,
        mod_id: int,
        old_level: str,
        new_level: str,
    ) -> None:
        """Log when mod changes server verification level."""
        if not self.enabled:
            return

        self._record_action(mod_id, "server_settings")

        embed = self._create_embed(
            title="Verification Level Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Before", value=old_level, inline=True)
        embed.add_field(name="After", value=new_level, inline=True)

        if await self._send_log(mod_id, embed, "Verification Level"):
            logger.tree("Mod Tracker: Verification Level Changed", [
                ("Mod ID", str(mod_id)),
                ("New Level", new_level),
            ], emoji="🔒")

    async def log_explicit_filter_change(
        self,
        mod_id: int,
        old_filter: str,
        new_filter: str,
    ) -> None:
        """Log when mod changes explicit content filter."""
        if not self.enabled:
            return

        self._record_action(mod_id, "server_settings")

        embed = self._create_embed(
            title="Explicit Content Filter Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Before", value=old_filter, inline=True)
        embed.add_field(name="After", value=new_filter, inline=True)

        if await self._send_log(mod_id, embed, "Explicit Filter"):
            logger.tree("Mod Tracker: Explicit Filter Changed", [
                ("Mod ID", str(mod_id)),
                ("New Filter", new_filter),
            ], emoji="🔞")

    async def log_2fa_requirement_change(
        self,
        mod_id: int,
        enabled: bool,
    ) -> None:
        """Log when mod changes 2FA requirement for moderation."""
        if not self.enabled:
            return

        self._record_action(mod_id, "server_settings")

        status = "Enabled" if enabled else "Disabled"
        color = EmbedColors.SUCCESS if enabled else EmbedColors.ERROR

        embed = self._create_embed(
            title="Mod 2FA Requirement Changed",
            color=color,
        )
        embed.add_field(name="Status", value=f"**{status}**", inline=True)

        if not enabled:
            embed.add_field(
                name="⚠️ Warning",
                value="Disabling 2FA requirement reduces server security!",
                inline=False,
            )

        if await self._send_log(mod_id, embed, "2FA Requirement"):
            logger.tree("Mod Tracker: 2FA Requirement Changed", [
                ("Mod ID", str(mod_id)),
                ("Status", status),
            ], emoji="🔐")

        # Alert if 2FA is disabled
        if not enabled:
            await self._send_alert(
                mod_id=mod_id,
                alert_type="2FA Requirement Disabled",
                description="Mod disabled the 2FA requirement for moderation actions.\n\n"
                           "This reduces server security and allows mods without 2FA to take actions.",
                color=EmbedColors.ERROR,
            )

    # =========================================================================
    # Soundboard Tracking
    # =========================================================================

    async def log_soundboard_create(
        self,
        mod_id: int,
        sound_name: str,
    ) -> None:
        """Log when mod creates a soundboard sound."""
        if not self.enabled:
            return

        self._record_action(mod_id, "soundboard")

        embed = self._create_embed(
            title="Soundboard Sound Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=f"`{sound_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Sound Create"):
            logger.tree("Mod Tracker: Sound Created", [
                ("Mod ID", str(mod_id)),
                ("Sound", sound_name),
            ], emoji="🔊")

    async def log_soundboard_delete(
        self,
        mod_id: int,
        sound_name: str,
    ) -> None:
        """Log when mod deletes a soundboard sound."""
        if not self.enabled:
            return

        self._record_action(mod_id, "soundboard")

        embed = self._create_embed(
            title="Soundboard Sound Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=f"`{sound_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Sound Delete"):
            logger.tree("Mod Tracker: Sound Deleted", [
                ("Mod ID", str(mod_id)),
                ("Sound", sound_name),
            ], emoji="🗑️")

    async def log_soundboard_update(
        self,
        mod_id: int,
        sound_name: str,
        changes: str,
    ) -> None:
        """Log when mod updates a soundboard sound."""
        if not self.enabled:
            return

        self._record_action(mod_id, "soundboard")

        embed = self._create_embed(
            title="Soundboard Sound Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Name", value=f"`{sound_name}`", inline=True)
        embed.add_field(name="Changes", value=changes, inline=False)

        if await self._send_log(mod_id, embed, "Sound Update"):
            logger.tree("Mod Tracker: Sound Updated", [
                ("Mod ID", str(mod_id)),
                ("Sound", sound_name),
            ], emoji="✏️")

    # =========================================================================
    # Onboarding Tracking
    # =========================================================================

    async def log_onboarding_create(
        self,
        mod_id: int,
    ) -> None:
        """Log when mod creates/enables onboarding."""
        if not self.enabled:
            return

        self._record_action(mod_id, "onboarding")

        embed = self._create_embed(
            title="Onboarding Enabled",
            color=EmbedColors.INFO,
        )
        embed.add_field(
            name="Description",
            value="Server onboarding has been enabled.",
            inline=False,
        )

        if await self._send_log(mod_id, embed, "Onboarding Create"):
            logger.tree("Mod Tracker: Onboarding Enabled", [
                ("Mod ID", str(mod_id)),
            ], emoji="👋")

    async def log_onboarding_update(
        self,
        mod_id: int,
        changes: str,
    ) -> None:
        """Log when mod updates onboarding settings."""
        if not self.enabled:
            return

        self._record_action(mod_id, "onboarding")

        embed = self._create_embed(
            title="Onboarding Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Changes", value=changes[:500], inline=False)

        if await self._send_log(mod_id, embed, "Onboarding Update"):
            logger.tree("Mod Tracker: Onboarding Updated", [
                ("Mod ID", str(mod_id)),
            ], emoji="✏️")

    async def log_onboarding_delete(
        self,
        mod_id: int,
    ) -> None:
        """Log when mod disables onboarding."""
        if not self.enabled:
            return

        self._record_action(mod_id, "onboarding")

        embed = self._create_embed(
            title="Onboarding Disabled",
            color=EmbedColors.ERROR,
        )
        embed.add_field(
            name="Description",
            value="Server onboarding has been disabled.",
            inline=False,
        )

        if await self._send_log(mod_id, embed, "Onboarding Delete"):
            logger.tree("Mod Tracker: Onboarding Disabled", [
                ("Mod ID", str(mod_id)),
            ], emoji="🗑️")

    # =========================================================================
    # Role Icon Tracking
    # =========================================================================

    async def log_role_icon_change(
        self,
        mod_id: int,
        role: discord.Role,
        action: str,  # "added", "changed", "removed"
    ) -> None:
        """Log when mod changes a role's icon."""
        if not self.enabled:
            return

        self._record_action(mod_id, "role_icon")

        color_map = {
            "added": EmbedColors.INFO,
            "changed": EmbedColors.WARNING,
            "removed": EmbedColors.ERROR,
        }

        embed = self._create_embed(
            title=f"Role Icon {action.title()}",
            color=color_map.get(action, EmbedColors.WARNING),
        )
        embed.add_field(name="Role", value=f"{role.mention} (`{role.name}`)", inline=True)

        # Show new icon if available
        if role.icon and action != "removed":
            embed.set_thumbnail(url=role.icon.url)

        if await self._send_log(mod_id, embed, f"Role Icon {action.title()}"):
            logger.tree(f"Mod Tracker: Role Icon {action.title()}", [
                ("Mod ID", str(mod_id)),
                ("Role", role.name),
            ], emoji="🎨")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ModTrackerService"]
