"""
Azab Discord Bot - Case Log Service
====================================

Service for logging mute/unmute actions to forum threads.

DESIGN:
    Each user gets a unique case thread when first muted.
    All subsequent mute/unmute events are logged to the same thread.
    Thread format: [XXXX] | Username

Features:
    - Unique case ID and thread per user
    - Mute/unmute events logged to same thread
    - Auto-unmutes (expired mutes) logged
    - Mute count tracked in embed titles
    - User profile pinned in first message

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, Tuple

import discord


def _has_valid_media_evidence(evidence: Optional[str]) -> bool:
    """
    Check if evidence contains a valid media attachment URL.

    Valid sources:
    - Discord CDN (cdn.discordapp.com, media.discordapp.net)
    - Direct image/video links (.png, .jpg, .gif, .mp4, .webm, etc.)

    Args:
        evidence: The evidence string to check.

    Returns:
        True if evidence contains valid media, False otherwise.
    """
    if not evidence:
        return False

    # Check for Discord CDN URLs
    discord_cdn_pattern = r'(cdn\.discordapp\.com|media\.discordapp\.net)/attachments/'
    if re.search(discord_cdn_pattern, evidence):
        return True

    # Check for direct media file extensions
    media_extensions = r'\.(png|jpg|jpeg|gif|webp|mp4|webm|mov|avi)(\?|$|\s)'
    if re.search(media_extensions, evidence, re.IGNORECASE):
        return True

    return False

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.views import (
    CASE_EMOJI,
    MESSAGE_EMOJI,
    DownloadButton,
    InfoButton,
    HistoryButton,
    ExtendButton,
    UnmuteButton,
    NotesButton,
)
from src.utils.retry import (
    retry_async,
    safe_fetch_channel,
    safe_fetch_message,
    safe_send,
    safe_edit,
    safe_delete,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# View Classes
# =============================================================================

class CaseLogView(discord.ui.View):
    """
    View with organized button rows for case log embeds.

    Row 0: Link buttons (Case, Message)
    Row 1: Info buttons (Info, Avatar, History, Notes)
    Row 2: Action buttons (Extend, Unmute) - mute embeds only
    """

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        message_url: Optional[str] = None,
        case_thread_id: Optional[int] = None,
        is_mute_embed: bool = False,
    ):
        super().__init__(timeout=None)

        # =================================================================
        # Row 0: Link buttons
        # =================================================================

        if case_thread_id:
            case_url = f"https://discord.com/channels/{guild_id}/{case_thread_id}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
                row=0,
            ))

        if message_url:
            self.add_item(discord.ui.Button(
                label="Message",
                url=message_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
                row=0,
            ))

        # =================================================================
        # Row 1: Info buttons
        # =================================================================

        info_btn = InfoButton(user_id, guild_id)
        info_btn.row = 1
        self.add_item(info_btn)

        avatar_btn = DownloadButton(user_id)
        avatar_btn.row = 1
        self.add_item(avatar_btn)

        history_btn = HistoryButton(user_id, guild_id)
        history_btn.row = 1
        self.add_item(history_btn)

        notes_btn = NotesButton(user_id, guild_id)
        notes_btn.row = 1
        self.add_item(notes_btn)

        # =================================================================
        # Row 2: Action buttons (mute embeds only)
        # =================================================================

        if is_mute_embed:
            extend_btn = ExtendButton(user_id, guild_id)
            extend_btn.row = 2
            self.add_item(extend_btn)

            unmute_btn = UnmuteButton(user_id, guild_id)
            unmute_btn.row = 2
            self.add_item(unmute_btn)


# =============================================================================
# Case Log Service
# =============================================================================

class CaseLogService:
    """
    Service for logging moderation actions to forum threads.

    DESIGN:
        Each user gets a unique case thread where all mute/unmute events
        are logged. Thread persists across all moderation actions for
        that user.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
        _forum: Cached forum channel reference.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    # Cache TTL for thread lookups (5 minutes)
    THREAD_CACHE_TTL = timedelta(minutes=5)
    # Debounce delay for profile stats updates (seconds)
    PROFILE_UPDATE_DEBOUNCE = 2.0

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the case log service.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._forum: Optional[discord.ForumChannel] = None
        self._forum_cache_time: Optional[datetime] = None
        # Thread cache: thread_id -> (thread, cached_at)
        self._thread_cache: Dict[int, Tuple[discord.Thread, datetime]] = {}
        # Pending reason scheduler
        self._reason_check_task: Optional[asyncio.Task] = None
        self._reason_check_running: bool = False
        # Debounced profile updates: user_id -> case_data
        self._pending_profile_updates: Dict[int, dict] = {}
        self._profile_update_task: Optional[asyncio.Task] = None

    # =========================================================================
    # Pending Reason Scheduler
    # =========================================================================

    async def start_reason_scheduler(self) -> None:
        """Start the background task for checking expired pending reasons."""
        if self._reason_check_task and not self._reason_check_task.done():
            self._reason_check_task.cancel()

        self._reason_check_running = True
        self._reason_check_task = asyncio.create_task(self._reason_check_loop())

        logger.tree("Pending Reason Scheduler Started", [
            ("Check Interval", "5 minutes"),
            ("Expiry Time", "1 hour"),
        ], emoji="⏰")

    async def stop_reason_scheduler(self) -> None:
        """Stop the pending reason scheduler."""
        self._reason_check_running = False

        if self._reason_check_task and not self._reason_check_task.done():
            self._reason_check_task.cancel()
            try:
                await self._reason_check_task
            except asyncio.CancelledError:
                pass

        logger.tree("Pending Reason Scheduler Stopped", [
            ("Status", "Inactive"),
        ], emoji="⏹️")

    async def _reason_check_loop(self) -> None:
        """Background loop to check for expired pending reasons."""
        await self.bot.wait_until_ready()

        while self._reason_check_running:
            try:
                await self._process_expired_reasons()
                await asyncio.sleep(300)  # Check every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Pending Reason Scheduler Error", [
                    ("Error", str(e)[:100]),
                ])
                await asyncio.sleep(300)

    async def _process_expired_reasons(self) -> None:
        """Process expired pending reasons and notify owner."""
        # Clean up old notified records (older than 24 hours)
        self.db.cleanup_old_pending_reasons(max_age_seconds=86400)

        expired = self.db.get_expired_pending_reasons(max_age_seconds=3600)  # 1 hour

        for pending in expired:
            try:
                thread = await self._get_case_thread(pending["thread_id"])
                if not thread:
                    # Thread gone, clean up
                    self.db.delete_pending_reason(pending["id"])
                    continue

                # Ping the owner
                owner_id = self.config.developer_id
                moderator_id = pending["moderator_id"]
                action_type = pending["action_type"]
                target_user_id = pending["target_user_id"]

                await safe_send(
                    thread,
                    f"⚠️ <@{owner_id}> **Alert:** <@{moderator_id}> did not provide a reason for "
                    f"this {action_type} on <@{target_user_id}> within 1 hour."
                )

                # Mark as notified so we don't ping again
                self.db.mark_pending_reason_notified(pending["id"])

                logger.tree("Owner Notified: Missing Reason", [
                    ("Thread ID", str(thread.id)),
                    ("Moderator ID", str(moderator_id)),
                    ("Action", action_type),
                    ("Target User ID", str(target_user_id)),
                ], emoji="⚠️")

            except Exception as e:
                logger.error("Failed To Notify Owner", [
                    ("Pending ID", str(pending["id"])),
                    ("Error", str(e)[:50]),
                ])

    # =========================================================================
    # Debounced Profile Updates
    # =========================================================================

    def _schedule_profile_update(self, user_id: int, case: dict) -> None:
        """
        Schedule a debounced profile stats update.

        DESIGN:
            Multiple rapid updates for the same user are coalesced.
            After PROFILE_UPDATE_DEBOUNCE seconds, all pending updates are processed.

        Args:
            user_id: User ID to update.
            case: Case data from database.
        """
        # Add/replace in pending updates
        self._pending_profile_updates[user_id] = case

        # Schedule processing if not already scheduled
        if self._profile_update_task is None or self._profile_update_task.done():
            self._profile_update_task = asyncio.create_task(self._process_profile_updates())

    async def _process_profile_updates(self) -> None:
        """Process all pending profile updates after debounce delay."""
        await asyncio.sleep(self.PROFILE_UPDATE_DEBOUNCE)

        # Take a snapshot and clear pending
        pending = self._pending_profile_updates.copy()
        self._pending_profile_updates.clear()

        if not pending:
            return

        # Process each pending update
        success_count = 0
        fail_count = 0
        for user_id, case in pending.items():
            try:
                await self._update_profile_stats(user_id, case)
                success_count += 1
            except Exception as e:
                fail_count += 1
                logger.warning(f"Failed to update profile stats for {user_id}: {str(e)[:50]}")

        logger.tree("PROFILE STATS UPDATED", [
            ("Processed", str(success_count)),
            ("Failed", str(fail_count)),
        ], emoji="📊")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if case logging is enabled."""
        return self.config.case_log_forum_id is not None

    def get_case_info(self, user_id: int) -> Optional[dict]:
        """
        Get case info for a user without logging.

        Args:
            user_id: Discord user ID.

        Returns:
            Dict with case_id and thread_id, or None if no case exists.
        """
        case = self.db.get_case_log(user_id)
        if case:
            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}
        return None

    async def prepare_case(self, user: discord.Member) -> Optional[dict]:
        """
        Prepare a case for a user (get or create without logging).

        Use this to get case_id for embeds before calling log_mute.

        Args:
            user: The Discord member.

        Returns:
            Dict with case_id and thread_id, or None if disabled/failed.
        """
        if not self.enabled:
            return None

        try:
            case = await self._get_or_create_case(user)
            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}
        except Exception as e:
            logger.error("Case Log: Failed To Prepare Case", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Forum Access
    # =========================================================================

    async def _get_forum(self) -> Optional[discord.ForumChannel]:
        """
        Get the case log forum channel with TTL-based caching.

        DESIGN:
            Caches forum reference with 5-minute TTL.
            Returns None if forum ID not configured or channel not found.

        Returns:
            Forum channel or None.
        """
        if not self.config.case_log_forum_id:
            return None

        now = datetime.now(NY_TZ)

        # Check if cache is still valid
        if self._forum is not None and self._forum_cache_time is not None:
            if now - self._forum_cache_time < self.THREAD_CACHE_TTL:
                return self._forum

        # Cache miss or expired - fetch forum with retry
        channel = await safe_fetch_channel(self.bot, self.config.case_log_forum_id)
        if channel is None:
            logger.warning(f"Failed To Get Case Log Forum: {self.config.case_log_forum_id}")
            return None

        if isinstance(channel, discord.ForumChannel):
            self._forum = channel
            self._forum_cache_time = now
            return self._forum

        logger.warning(f"Channel {self.config.case_log_forum_id} is not a ForumChannel")
        return None

    async def _get_case_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """
        Get a case thread by ID with TTL-based caching.

        Args:
            thread_id: The thread ID.

        Returns:
            The thread, or None if not found.
        """
        now = datetime.now(NY_TZ)

        # Check cache first
        if thread_id in self._thread_cache:
            cached_thread, cached_at = self._thread_cache[thread_id]
            if now - cached_at < self.THREAD_CACHE_TTL:
                return cached_thread
            else:
                # Cache expired, remove it
                del self._thread_cache[thread_id]

        # Cache miss - fetch thread with retry
        channel = await safe_fetch_channel(self.bot, thread_id)
        if channel is None:
            logger.warning(f"Case Thread Not Found: {thread_id}")
            return None

        if isinstance(channel, discord.Thread):
            # Cache the result
            self._thread_cache[thread_id] = (channel, now)
            # Cleanup old cache entries (keep max 100)
            if len(self._thread_cache) > 100:
                oldest = min(self._thread_cache.keys(), key=lambda k: self._thread_cache[k][1])
                del self._thread_cache[oldest]
            return channel

        logger.warning(f"Channel {thread_id} is not a Thread: {type(channel)}")
        return None

    # =========================================================================
    # Mute Logging
    # =========================================================================

    async def log_mute(
        self,
        user: discord.Member,
        moderator: discord.Member,
        duration: str,
        reason: Optional[str] = None,
        source_message_url: Optional[str] = None,
        is_extension: bool = False,
        evidence: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Log a mute action to the user's case thread.

        DESIGN:
            Creates new case thread if user has no existing case.
            Increments mute count and logs event to existing case.

        Args:
            user: The user being muted.
            moderator: The moderator who issued the mute.
            duration: Duration display string.
            reason: Optional reason for the mute.
            source_message_url: Optional URL to the mute message in server.
            is_extension: Whether this is extending an existing mute.
            evidence: Optional evidence link or description.

        Returns:
            Dict with case_id and thread_id, or None if disabled/failed.
        """
        if not self.enabled:
            return None

        try:
            case = await self._get_or_create_case(user, duration, moderator.id)

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                logger.warning(f"log_mute: Thread {case['thread_id']} not found, returning early")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            # Determine mute count (don't increment for extensions)
            if case.get("just_created"):
                mute_count = 1
            elif is_extension:
                # Get current count without incrementing, but update last mute info
                case_data = self.db.get_case_log(user.id)
                mute_count = case_data["mute_count"] if case_data else 1
                # Update last mute info for extensions too
                self.db.execute(
                    """UPDATE case_logs SET last_mute_at = ?, last_mute_duration = ?,
                       last_mute_moderator_id = ? WHERE user_id = ?""",
                    (datetime.now(NY_TZ).timestamp(), duration, moderator.id, user.id)
                )
            else:
                mute_count = self.db.increment_mute_count(user.id, duration, moderator.id)

            # Calculate expiry time for non-permanent mutes
            expires_at = None
            duration_seconds = self._parse_duration_to_seconds(duration)
            if duration_seconds:
                expires_at = datetime.now(NY_TZ) + timedelta(seconds=duration_seconds)

            # If evidence provided, send it as a separate message first to preserve it
            evidence_message_url = None
            if evidence and _has_valid_media_evidence(evidence):
                evidence_msg = await safe_send(case_thread, f"📎 **Evidence:**\n{evidence}")
                if evidence_msg:
                    evidence_message_url = evidence_msg.jump_url

            # Build and send mute embed with jump button and download
            embed = self._build_mute_embed(user, moderator, duration, reason, mute_count, is_extension, evidence_message_url, expires_at)
            view = CaseLogView(
                user_id=user.id,
                guild_id=user.guild.id,
                message_url=source_message_url,
                case_thread_id=case["thread_id"],
                is_mute_embed=True,  # Include Extend and Unmute buttons
            )
            embed_message = await safe_send(case_thread, embed=embed, view=view)
            if not embed_message:
                logger.warning(f"log_mute: Failed to send embed to thread {case_thread.id}")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            # If no valid media evidence provided, ping moderator for attachment
            if not _has_valid_media_evidence(evidence):
                action_type = "extension" if is_extension else "mute"
                warning_message = await safe_send(
                    case_thread,
                    f"⚠️ {moderator.mention} No screenshot/video evidence was provided for this {action_type}.\n\n"
                    f"**Reply to this message** with an attachment (screenshot/video).\n\n"
                    f"You have **1 hour** or the owner will be notified.\n"
                    f"_Only replies from you will be accepted._"
                )
                # Track pending evidence in database (only if warning sent)
                if warning_message:
                    self.db.create_pending_reason(
                        thread_id=case_thread.id,
                        warning_message_id=warning_message.id,
                        embed_message_id=embed_message.id,
                        moderator_id=moderator.id,
                        target_user_id=user.id,
                        action_type=action_type,
                    )

            # Repeat offender alert at 3+ mutes (not for extensions)
            if not is_extension:
                is_permanent = duration.lower() in ("permanent", "perm", "forever")
                if mute_count >= 3 and not is_permanent:
                    alert_embed = discord.Embed(
                        title="⚠️ Repeat Offender Alert",
                        color=EmbedColors.WARNING,
                        description=f"**{user.display_name}** has been muted **{mute_count} times**.\n\nConsider a longer mute duration for this user.",
                        timestamp=datetime.now(NY_TZ),
                    )
                    alert_embed.set_footer(text=f"Alert • ID: {user.id}")
                    await safe_send(case_thread, embed=alert_embed)

            if is_extension:
                log_type = "Mute Extended"
            elif case.get("just_created"):
                log_type = "New Case Created With Mute"
            else:
                log_type = "Mute Logged"

            logger.tree(f"Case Log: {log_type}", [
                ("User", f"{user.display_name} ({user.id})"),
                ("Case ID", case['case_id']),
                ("Muted By", f"{moderator.display_name}"),
                ("Duration", duration),
                ("Mute #", str(mute_count)),
                ("Reason", reason if reason else "Not provided"),
            ], emoji="🔇")

            # Schedule debounced profile stats update
            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                self._schedule_profile_update(user.id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute", [
                ("User ID", str(user.id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:200]),
            ])
            import traceback
            return None

    # =========================================================================
    # Warning Logging
    # =========================================================================

    async def log_warn(
        self,
        user: discord.Member,
        moderator: discord.Member,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        active_warns: int = 1,
        total_warns: int = 1,
        source_message_url: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Log a warning action to the user's case thread.

        Args:
            user: The user being warned.
            moderator: The moderator who issued the warning.
            reason: Optional reason for the warning.
            evidence: Optional evidence link or description.
            active_warns: Active (non-expired) warning count.
            total_warns: Total warning count (all time).
            source_message_url: Optional URL to the warn message in server.

        Returns:
            Dict with case_id and thread_id, or None if disabled/failed.
        """
        if not self.enabled:
            return None

        try:
            case = await self._get_or_create_case(user)

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                logger.warning(f"log_warn: Thread {case['thread_id']} not found, returning early")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            # Increment warn count in case_logs
            if not case.get("just_created"):
                self.db.increment_warn_count(user.id, moderator.id)

            # If evidence provided, send it as a separate message first to preserve it
            evidence_message_url = None
            if evidence and _has_valid_media_evidence(evidence):
                evidence_msg = await safe_send(case_thread, f"📎 **Evidence:**\n{evidence}")
                if evidence_msg:
                    evidence_message_url = evidence_msg.jump_url

            # Build and send warn embed
            embed = self._build_warn_embed(user, moderator, reason, active_warns, total_warns, evidence_message_url)
            view = CaseLogView(
                user_id=user.id,
                guild_id=user.guild.id,
                message_url=source_message_url,
                case_thread_id=case["thread_id"],
                is_mute_embed=False,
            )
            embed_message = await safe_send(case_thread, embed=embed, view=view)
            if not embed_message:
                logger.warning(f"log_warn: Failed to send embed to thread {case_thread.id}")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            # If no valid media evidence provided, ping moderator for attachment
            if not _has_valid_media_evidence(evidence):
                warning_message = await safe_send(
                    case_thread,
                    f"⚠️ {moderator.mention} No screenshot/video evidence was provided for this warning.\n\n"
                    f"**Reply to this message** with an attachment (screenshot/video).\n\n"
                    f"You have **1 hour** or the owner will be notified.\n"
                    f"_Only replies from you will be accepted._"
                )
                if warning_message:
                    self.db.create_pending_reason(
                        thread_id=case_thread.id,
                        warning_message_id=warning_message.id,
                        embed_message_id=embed_message.id,
                        moderator_id=moderator.id,
                        target_user_id=user.id,
                        action_type="warn",
                    )

            # Repeat offender alert at 3+ active warnings
            if active_warns >= 3:
                alert_embed = discord.Embed(
                    title="⚠️ Repeat Offender Alert",
                    color=EmbedColors.WARNING,
                    description=f"**{user.display_name}** has **{active_warns} active warnings**.\n\nConsider a mute or ban for this user.",
                    timestamp=datetime.now(NY_TZ),
                )
                alert_embed.set_footer(text=f"Alert • ID: {user.id}")
                await safe_send(case_thread, embed=alert_embed)

            if case.get("just_created"):
                log_type = "New Case Created With Warning"
            else:
                log_type = "Warning Logged"

            logger.tree(f"Case Log: {log_type}", [
                ("User", f"{user.display_name} ({user.id})"),
                ("Case ID", case['case_id']),
                ("Warned By", f"{moderator.display_name}"),
                ("Active Warnings", str(active_warns)),
                ("Total Warnings", str(total_warns)),
                ("Reason", reason if reason else "Not provided"),
            ], emoji="⚠️")

            # Schedule debounced profile stats update
            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                self._schedule_profile_update(user.id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Warning", [
                ("User ID", str(user.id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:200]),
            ])
            return None

    def _build_warn_embed(
        self,
        user: discord.Member,
        moderator: discord.Member,
        reason: Optional[str] = None,
        active_warns: int = 1,
        total_warns: int = 1,
        evidence: Optional[str] = None,
    ) -> discord.Embed:
        """
        Build a warning action embed.

        Args:
            user: The user being warned.
            moderator: The moderator who issued the warning.
            reason: Optional reason for the warning.
            active_warns: Active (non-expired) warning count.
            total_warns: Total warning count (all time).
            evidence: Optional evidence link or description.

        Returns:
            Discord Embed for the warning action.
        """
        if active_warns > 1:
            title = f"⚠️ User Warned (Warning #{active_warns})"
        else:
            title = "⚠️ User Warned"

        embed = discord.Embed(
            title=title,
            color=EmbedColors.WARNING,
            timestamp=datetime.now(NY_TZ),
        )
        embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Warned By", value=f"`{moderator.display_name}`", inline=True)

        # Show active vs total if there are expired warnings
        if active_warns != total_warns:
            embed.add_field(name="Warnings", value=f"`{active_warns}` active (`{total_warns}` total)", inline=True)
        else:
            embed.add_field(name="Warning #", value=f"`{active_warns}`", inline=True)

        # Account Age with warning for new accounts
        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
        account_age_days = (now - created_at).days
        age_str = self._format_age(created_at, now)

        if account_age_days < 7:
            embed.add_field(name="Account Age", value=f"`{age_str}` ⚠️", inline=True)
        elif account_age_days < 30:
            embed.add_field(name="Account Age", value=f"`{age_str}` ⚡", inline=True)
        else:
            embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

        # Get previous mute/ban counts for context
        mute_count = self.db.get_case_log(user.id)
        if mute_count:
            mc = mute_count.get("mute_count", 0) or 0
            bc = mute_count.get("ban_count", 0) or 0
            if mc > 0 or bc > 0:
                embed.add_field(name="Previous Mutes", value=f"`{mc}`", inline=True)
                embed.add_field(name="Previous Bans", value=f"`{bc}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        else:
            embed.add_field(name="Reason", value="*Not provided*", inline=False)

        # Evidence: link to the evidence message in the case thread
        if evidence:
            embed.add_field(name="Evidence", value=f"[View Evidence]({evidence})", inline=False)

        set_footer(embed)
        return embed

    # =========================================================================
    # Unmute Logging
    # =========================================================================

    async def log_unmute(
        self,
        user_id: int,
        moderator: discord.Member,
        display_name: str,
        reason: Optional[str] = None,
        source_message_url: Optional[str] = None,
        user_avatar_url: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Log an unmute action to the user's case thread.

        Args:
            user_id: The user being unmuted.
            moderator: The moderator who issued the unmute.
            display_name: Display name of the user.
            reason: Optional reason for the unmute.
            source_message_url: Optional URL to the unmute message in server.
            user_avatar_url: Optional avatar URL (avoids API call if provided).

        Returns:
            Dict with case_id and thread_id, or None if no case exists.
        """
        if not self.enabled:
            return None

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                # No case exists, nothing to log
                return None

            # Get last mute info BEFORE updating unmute timestamp
            last_mute_info = self.db.get_last_mute_info(user_id)

            # Calculate "was muted for" duration
            time_served = None
            original_duration = None
            original_moderator_name = None

            if last_mute_info and last_mute_info.get("last_mute_at"):
                muted_at = last_mute_info["last_mute_at"]
                now = datetime.now(NY_TZ).timestamp()
                time_served_seconds = now - muted_at
                time_served = self._format_duration_precise(time_served_seconds)
                original_duration = last_mute_info.get("last_mute_duration")

                # Get original moderator name
                original_mod_id = last_mute_info.get("last_mute_moderator_id")
                if original_mod_id and moderator.guild:
                    original_mod = moderator.guild.get_member(original_mod_id)
                    if original_mod:
                        original_moderator_name = original_mod.display_name
                    else:
                        original_moderator_name = f"Unknown ({original_mod_id})"

            # Update last unmute timestamp
            self.db.update_last_unmute(user_id)

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = self._build_unmute_embed(
                    moderator=moderator,
                    reason=reason,
                    user_avatar_url=user_avatar_url,
                    time_served=time_served,
                    original_duration=original_duration,
                    original_moderator_name=original_moderator_name,
                )
                view = CaseLogView(
                    user_id=user_id,
                    guild_id=moderator.guild.id,
                    message_url=source_message_url,
                    case_thread_id=case["thread_id"],
                )
                embed_message = await safe_send(case_thread, embed=embed, view=view)
                if not embed_message:
                    logger.warning(f"log_unmute: Failed to send embed to thread {case_thread.id}")
                    return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

                # If no reason provided, ping moderator and track pending reason
                if not reason:
                    warning_message = await safe_send(
                        case_thread,
                        f"⚠️ {moderator.mention} No reason was provided for this unmute.\n\n"
                        f"**Reply to this message** with the reason.\n"
                        f"You have **1 hour** or the owner will be notified.\n"
                        f"_Only replies from you will be accepted._"
                    )
                    # Track pending reason in database (only if warning sent)
                    if warning_message:
                        self.db.create_pending_reason(
                            thread_id=case_thread.id,
                            warning_message_id=warning_message.id,
                            embed_message_id=embed_message.id,
                            moderator_id=moderator.id,
                            target_user_id=user_id,
                            action_type="unmute",
                        )

                logger.tree("Case Log: Unmute Logged", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                    ("Unmuted By", f"{moderator.display_name}"),
                    ("Reason", reason if reason else "Not provided"),
                ], emoji="🔊")

                # Schedule debounced profile stats update
                updated_case = self.db.get_case_log(user_id)
                if updated_case:
                    self._schedule_profile_update(user_id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Unmute", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Timeout Logging
    # =========================================================================

    async def log_timeout(
        self,
        user: discord.Member,
        moderator_id: int,
        until: datetime,
        reason: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Log a timeout action to the user's case thread.

        Args:
            user: The user being timed out.
            moderator_id: ID of the moderator who issued the timeout.
            until: When the timeout expires.
            reason: Optional reason for the timeout.

        Returns:
            Dict with case_id and thread_id, or None if disabled/failed.
        """
        if not self.enabled:
            return None

        try:
            case = await self._get_or_create_case(user)

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                logger.warning(f"log_timeout: Thread {case['thread_id']} not found")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            # Get moderator name
            guild = user.guild
            moderator = guild.get_member(moderator_id)
            mod_name = moderator.display_name if moderator else f"Mod ({moderator_id})"

            # Calculate duration string
            now = datetime.now(NY_TZ)
            until_aware = until.replace(tzinfo=NY_TZ) if until.tzinfo is None else until
            delta = until_aware - now
            if delta.days > 0:
                duration = f"{delta.days}d {delta.seconds // 3600}h"
            elif delta.seconds >= 3600:
                duration = f"{delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
            else:
                duration = f"{delta.seconds // 60}m"

            # Increment mute count (timeouts count as mutes)
            if case.get("just_created"):
                mute_count = 1
            else:
                mute_count = self.db.increment_mute_count(user.id)

            # Build and send timeout embed
            embed = self._build_timeout_embed(user, mod_name, duration, until, reason, mute_count, moderator)
            view = CaseLogView(
                user_id=user.id,
                guild_id=user.guild.id,
                message_url=None,
                case_thread_id=case["thread_id"],
                is_mute_embed=True,  # Include Extend and Unmute buttons
            )
            await safe_send(case_thread, embed=embed, view=view)

            logger.tree("Case Log: Timeout Logged", [
                ("User", f"{user.display_name} ({user.id})"),
                ("Case ID", case['case_id']),
                ("Timeout By", mod_name),
                ("Duration", duration),
                ("Mute #", str(mute_count)),
            ], emoji="⏰")

            # Schedule debounced profile stats update
            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                self._schedule_profile_update(user.id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Timeout", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Ban Logging
    # =========================================================================

    async def log_ban(
        self,
        user: discord.Member,
        moderator: discord.Member,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        source_message_url: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Log a ban action to the user's case thread.

        Args:
            user: The user being banned.
            moderator: The moderator who issued the ban.
            reason: Optional reason for the ban.
            evidence: Optional evidence link.
            source_message_url: Optional URL to the ban message in server.

        Returns:
            Dict with case_id and thread_id, or None if failed.
        """
        if not self.enabled:
            return None

        try:
            case = await self._get_or_create_case(user)

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                logger.warning(f"log_ban: Thread {case['thread_id']} not found, returning early")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            now = datetime.now(NY_TZ)

            # If evidence provided, send it as a separate message first to preserve it
            evidence_message_url = None
            if evidence and _has_valid_media_evidence(evidence):
                evidence_msg = await safe_send(case_thread, f"📎 **Evidence:**\n{evidence}")
                if evidence_msg:
                    evidence_message_url = evidence_msg.jump_url

            # Get ban count for this user
            ban_count = self.db.get_user_ban_count(user.id, user.guild.id)

            # Build title with ban count if > 1
            if ban_count > 0:
                title = f"🔨 User Banned (Ban #{ban_count + 1})"
            else:
                title = "🔨 User Banned"

            embed = discord.Embed(
                title=title,
                color=EmbedColors.ERROR,
                timestamp=now,
            )
            embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Banned By", value=f"`{moderator.display_name}`", inline=True)

            # Account Age with warning for new accounts
            created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
            account_age_days = (now - created_at).days
            age_str = self._format_age(created_at, now)

            if account_age_days < 7:
                embed.add_field(name="Account Age", value=f"`{age_str}` ⚠️", inline=True)
            elif account_age_days < 30:
                embed.add_field(name="Account Age", value=f"`{age_str}` ⚡", inline=True)
            else:
                embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

            # Server Join Date
            if hasattr(user, "joined_at") and user.joined_at:
                embed.add_field(name="Server Joined", value=f"<t:{int(user.joined_at.timestamp())}:R>", inline=True)

            # Previous Bans (only show if > 0)
            if ban_count > 0:
                embed.add_field(name="Previous Bans", value=f"`{ban_count}`", inline=True)

            if reason:
                embed.add_field(name="Reason", value=f"```{reason}```", inline=False)
            else:
                embed.add_field(name="Reason", value="```No reason provided```", inline=False)

            # Evidence: link to the evidence message in the case thread
            if evidence_message_url:
                embed.add_field(name="Evidence", value=f"[View Evidence]({evidence_message_url})", inline=False)

            embed.set_footer(text=f"Ban • ID: {user.id}")

            view = CaseLogView(
                user_id=user.id,
                guild_id=user.guild.id,
                message_url=source_message_url,
                case_thread_id=case["thread_id"],
            )
            embed_message = await safe_send(case_thread, embed=embed, view=view)
            if not embed_message:
                logger.warning(f"log_ban: Failed to send embed to thread {case_thread.id}")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            # If no valid media evidence provided, ping moderator for attachment
            if not _has_valid_media_evidence(evidence):
                warning_message = await safe_send(
                    case_thread,
                    f"⚠️ {moderator.mention} No screenshot/video evidence was provided for this ban.\n\n"
                    f"**Reply to this message** with an attachment (screenshot/video).\n\n"
                    f"You have **1 hour** or the owner will be notified.\n"
                    f"_Only replies from you will be accepted._"
                )
                # Track pending evidence in database (only if warning sent)
                if warning_message:
                    self.db.create_pending_reason(
                        thread_id=case_thread.id,
                        warning_message_id=warning_message.id,
                        embed_message_id=embed_message.id,
                        moderator_id=moderator.id,
                        target_user_id=user.id,
                        action_type="ban",
                    )

            logger.tree("Case Log: Ban Logged", [
                ("User", f"{user} ({user.id})"),
                ("Case ID", case['case_id']),
                ("Banned By", f"{moderator.display_name}"),
            ], emoji="🔨")

            # Schedule debounced profile stats update
            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                self._schedule_profile_update(user.id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Ban", [
                ("User ID", str(user.id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:200]),
            ])
            import traceback
            return None

    async def log_unban(
        self,
        user_id: int,
        username: str,
        moderator: discord.Member,
        reason: Optional[str] = None,
        source_message_url: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Log an unban action to the user's case thread.

        Args:
            user_id: The user being unbanned.
            username: Username of the unbanned user.
            moderator: The moderator who issued the unban.
            reason: Optional reason for the unban.
            source_message_url: Optional URL to the unban message in server.

        Returns:
            Dict with case_id and thread_id, or None if no case exists.
        """
        if not self.enabled:
            return None

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return None

            # Get last ban info BEFORE we might update anything
            last_ban_info = self.db.get_last_ban_info(user_id)

            # Calculate ban context
            time_banned = None
            original_moderator_name = None
            original_reason = None

            if last_ban_info and last_ban_info.get("last_ban_at"):
                banned_at = last_ban_info["last_ban_at"]
                now_ts = datetime.now(NY_TZ).timestamp()
                time_banned_seconds = now_ts - banned_at
                time_banned = self._format_duration_precise(time_banned_seconds)
                original_reason = last_ban_info.get("last_ban_reason")

                # Get original moderator name
                original_mod_id = last_ban_info.get("last_ban_moderator_id")
                if original_mod_id and moderator.guild:
                    original_mod = moderator.guild.get_member(original_mod_id)
                    if original_mod:
                        original_moderator_name = original_mod.display_name
                    else:
                        original_moderator_name = f"Unknown ({original_mod_id})"

            case_thread = await self._get_case_thread(case["thread_id"])

            if case_thread:
                now = datetime.now(NY_TZ)

                embed = discord.Embed(
                    title="🔓 User Unbanned",
                    color=EmbedColors.SUCCESS,
                    timestamp=now,
                )
                embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
                embed.add_field(name="Unbanned By", value=f"`{moderator.display_name}`", inline=True)

                # Time banned (how long the ban lasted)
                if time_banned:
                    embed.add_field(name="Banned For", value=f"`{time_banned}`", inline=True)

                # Originally banned by
                if original_moderator_name:
                    embed.add_field(name="Originally Banned By", value=f"`{original_moderator_name}`", inline=True)

                # Original reason
                if original_reason:
                    embed.add_field(name="Original Reason", value=f"```{original_reason[:200]}```", inline=False)

                if reason:
                    embed.add_field(name="Unban Reason", value=f"```{reason}```", inline=False)

                embed.set_footer(text=f"Unban • ID: {user_id}")

                view = CaseLogView(
                    user_id=user_id,
                    guild_id=moderator.guild.id,
                    message_url=source_message_url,
                    case_thread_id=case["thread_id"],
                )
                embed_message = await safe_send(case_thread, embed=embed, view=view)
                if not embed_message:
                    logger.warning(f"log_unban: Failed to send embed to thread {case_thread.id}")
                    return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

                # If no reason provided, ping moderator and track pending reason
                if not reason:
                    warning_message = await safe_send(
                        case_thread,
                        f"⚠️ {moderator.mention} No reason was provided for this unban.\n\n"
                        f"**Reply to this message** with the reason.\n"
                        f"You have **1 hour** or the owner will be notified.\n"
                        f"_Only replies from you will be accepted._"
                    )
                    # Track pending reason in database (only if warning sent)
                    if warning_message:
                        self.db.create_pending_reason(
                            thread_id=case_thread.id,
                            warning_message_id=warning_message.id,
                            embed_message_id=embed_message.id,
                            moderator_id=moderator.id,
                            target_user_id=user_id,
                            action_type="unban",
                        )

                logger.tree("Case Log: Unban Logged", [
                    ("User", f"{username} ({user_id})"),
                    ("Case ID", case['case_id']),
                    ("Unbanned By", f"{moderator.display_name}"),
                ], emoji="🔓")

                # Schedule debounced profile stats update
                updated_case = self.db.get_case_log(user_id)
                if updated_case:
                    self._schedule_profile_update(user_id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Unban", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])
            return None

    async def log_mute_expired(
        self,
        user_id: int,
        display_name: str,
        user_avatar_url: Optional[str] = None,
    ) -> None:
        """
        Log an auto-unmute (expired mute) to the user's case thread.

        Args:
            user_id: The user whose mute expired.
            display_name: Display name of the user.
            user_avatar_url: Optional avatar URL (avoids API call if provided).
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return

            # Update last unmute timestamp
            self.db.update_last_unmute(user_id)

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = self._build_expired_embed(user_avatar_url)
                view = CaseLogView(
                    user_id=user_id,
                    guild_id=case_thread.guild.id,
                    case_thread_id=case["thread_id"],
                )
                await safe_send(case_thread, embed=embed, view=view)

                logger.tree("Case Log: Mute Expiry Logged", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                ], emoji="⏰")

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute Expiry", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    async def log_member_left_muted(
        self,
        user_id: int,
        display_name: str,
        muted_at: float,
        avatar_url: Optional[str] = None,
    ) -> None:
        """
        Log when a muted user leaves the server.

        Args:
            user_id: The user who left.
            display_name: Display name of the user.
            muted_at: Timestamp when the user was muted.
            avatar_url: Optional avatar URL of the user.
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return

            # Get muted by info
            last_mute_info = self.db.get_last_mute_info(user_id)
            muted_by_name = None

            if last_mute_info and last_mute_info.get("last_mute_moderator_id"):
                mod_id = last_mute_info["last_mute_moderator_id"]
                # Try to get mod name from any guild the bot is in
                for guild in self.bot.guilds:
                    mod = guild.get_member(mod_id)
                    if mod:
                        muted_by_name = mod.display_name
                        break
                if not muted_by_name:
                    muted_by_name = f"Unknown ({mod_id})"

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                now = datetime.now(NY_TZ)

                embed = discord.Embed(
                    title="🚪 Left Server While Muted",
                    description="User left the server with an active mute.",
                    color=EmbedColors.WARNING,
                    timestamp=now,
                )

                # Set thumbnail
                if avatar_url:
                    embed.set_thumbnail(url=avatar_url)

                # Calculate time since muted
                time_since_mute = now.timestamp() - muted_at
                duration_str = self._format_duration_precise(time_since_mute)
                embed.add_field(
                    name="Left After",
                    value=f"`{duration_str}`",
                    inline=True,
                )

                # Muted by
                if muted_by_name:
                    embed.add_field(
                        name="Muted By",
                        value=f"`{muted_by_name}`",
                        inline=True,
                    )

                embed.set_footer(text=f"Leave • ID: {user_id}")

                # Add Info and Avatar buttons
                view = CaseLogView(
                    user_id=user_id,
                    guild_id=case_thread.guild.id,
                )
                await safe_send(case_thread, embed=embed, view=view)

                logger.tree("Case Log: Member Left Muted", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                    ("Left After", duration_str),
                ], emoji="🚪")

        except Exception as e:
            logger.error("Case Log: Failed To Log Member Left", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    def _format_duration_precise(self, seconds: float) -> str:
        """
        Format duration with precision (seconds, minutes, hours, days).

        Args:
            seconds: Duration in seconds.

        Returns:
            Human-readable duration string.
        """
        seconds = int(seconds)

        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            if hours > 0:
                return f"{days}d {hours}h"
            return f"{days} day{'s' if days != 1 else ''}"

    async def log_mute_evasion_return(
        self,
        member: discord.Member,
        moderator_ids: list[int],
    ) -> None:
        """
        Log when a muted user rejoins the server (mute evasion attempt).

        Pings all moderators who muted/extended this user.

        Args:
            member: The member who rejoined.
            moderator_ids: List of moderator IDs who muted this user.
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(member.id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                now = datetime.now(NY_TZ)

                embed = discord.Embed(
                    title="⚠️ Rejoined While Muted",
                    description="User rejoined the server with an active mute. Muted role has been re-applied.",
                    color=EmbedColors.WARNING,
                    timestamp=now,
                )

                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"Rejoin • ID: {member.id}")

                # Include Extend/Unmute since user is still muted
                view = CaseLogView(
                    user_id=member.id,
                    guild_id=member.guild.id,
                    case_thread_id=case["thread_id"],
                    is_mute_embed=True,  # User is still muted
                )
                await safe_send(case_thread, embed=embed, view=view)

                # Ping all moderators who muted this user
                if moderator_ids:
                    pings = " ".join(f"<@{mod_id}>" for mod_id in moderator_ids)
                    await safe_send(case_thread, pings)

                logger.tree("Case Log: Mute Evasion Return", [
                    ("User", f"{member} ({member.id})"),
                    ("Case ID", case['case_id']),
                    ("Mods Pinged", str(len(moderator_ids))),
                ], emoji="⚠️")

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute Evasion", [
                ("User ID", str(member.id)),
                ("Error", str(e)[:100]),
            ])

    async def log_muted_vc_violation(
        self,
        user_id: int,
        display_name: str,
        channel_name: str,
        avatar_url: Optional[str] = None,
    ) -> None:
        """
        Log when a muted user attempts to join voice and gets timed out.

        Args:
            user_id: The user's Discord ID.
            display_name: The user's display name.
            channel_name: The voice channel they attempted to join.
            avatar_url: Optional avatar URL of the user.
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                now = datetime.now(NY_TZ)

                embed = discord.Embed(
                    title="🔇 Voice Channel Violation",
                    description="User attempted to join a voice channel while muted. They have been disconnected and given a 1-hour timeout.",
                    color=EmbedColors.ERROR,
                    timestamp=now,
                )

                # Set thumbnail
                if avatar_url:
                    embed.set_thumbnail(url=avatar_url)

                embed.add_field(
                    name="Attempted Channel",
                    value=f"`{channel_name}`",
                    inline=True,
                )
                embed.add_field(
                    name="Action Taken",
                    value="`Disconnected + 1h Timeout`",
                    inline=True,
                )

                embed.set_footer(text=f"Violation • ID: {user_id}")

                # Add buttons - include Extend/Unmute since user is still muted
                view = CaseLogView(
                    user_id=user_id,
                    guild_id=case_thread.guild.id,
                    is_mute_embed=True,  # User is still muted
                )
                await safe_send(case_thread, embed=embed, view=view)

                logger.tree("Case Log: VC Violation", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                    ("Channel", channel_name),
                ], emoji="🔇")

        except Exception as e:
            logger.error("Case Log: Failed To Log VC Violation", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    # =========================================================================
    # Case Management
    # =========================================================================

    async def _get_or_create_case(
        self,
        user: discord.Member,
        duration: Optional[str] = None,
        moderator_id: Optional[int] = None,
    ) -> dict:
        """
        Get existing case or create new one with forum thread.

        Args:
            user: The user to get/create case for.
            duration: Optional duration string for initial mute.
            moderator_id: Optional moderator ID for initial mute.

        Returns:
            Dict with case info, includes 'just_created' flag if new.
        """
        case = self.db.get_case_log(user.id)
        if case:
            return case  # Existing case

        # Create new case
        case_id = self.db.get_next_case_id()

        thread = await self._create_case_thread(user, case_id)

        if thread:
            self.db.create_case_log(user.id, case_id, thread.id, duration, moderator_id)
            # Cache the thread immediately so we don't need to fetch it again
            self._thread_cache[thread.id] = (thread, datetime.now(NY_TZ))

            logger.tree("CASE THREAD CREATED", [
                ("User", f"{user} ({user.id})"),
                ("Case ID", case_id),
                ("Thread ID", str(thread.id)),
            ], emoji="📂")

            return {
                "user_id": user.id,
                "case_id": case_id,
                "thread_id": thread.id,
                "just_created": True,
            }

        logger.error(f"_get_or_create_case: Failed to create thread for user {user.id}, case_id={case_id}")
        raise RuntimeError("Failed to create case thread")

    async def _create_case_thread(
        self,
        user: discord.Member,
        case_id: str,
    ) -> Optional[discord.Thread]:
        """
        Create a new forum thread for this case.

        DESIGN:
            Thread includes user profile embed only.
            Mute embed is sent separately to include jump button.
            User profile is pinned for easy reference.

        Args:
            user: The user the case is for.
            case_id: The unique 4-character alphanumeric case ID.

        Returns:
            The created thread, or None on failure.
        """
        forum = await self._get_forum()
        if not forum:
            logger.warning(f"_create_case_thread: Forum not found, cannot create thread")
            return None

        # Build user profile embed
        user_embed = discord.Embed(
            title="📋 User Profile",
            color=EmbedColors.INFO,
            timestamp=datetime.now(NY_TZ),
        )
        user_embed.set_thumbnail(url=user.display_avatar.url)
        user_embed.add_field(name="Username", value=f"{user.name}", inline=True)
        user_embed.add_field(name="Display Name", value=f"{user.display_name}", inline=True)
        user_embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)

        # Discord account creation date
        user_embed.add_field(
            name="Discord Joined",
            value=f"<t:{int(user.created_at.timestamp())}:F>",
            inline=True,
        )

        # Server join date
        if hasattr(user, "joined_at") and user.joined_at:
            user_embed.add_field(
                name="Server Joined",
                value=f"<t:{int(user.joined_at.timestamp())}:F>",
                inline=True,
            )

        # Account age
        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
        account_age = self._format_age(created_at, now)
        user_embed.add_field(name="Account Age", value=account_age, inline=True)

        # Previous names (if any)
        previous_names = self.db.get_previous_names(user.id, limit=3)
        if previous_names:
            names_str = ", ".join(f"`{name}`" for name in previous_names)
            user_embed.add_field(name="Previous Names", value=names_str, inline=False)

        set_footer(user_embed)

        # Create thread with user profile only
        thread_name = f"[{case_id}] | {user.display_name}"

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],  # Discord limit
                embed=user_embed,
            )

            # Pin the first message (user profile) and store its ID
            try:
                if thread_with_msg.message:
                    await thread_with_msg.message.pin()
                    # Store the message ID for future updates
                    self.db.set_profile_message_id(user.id, thread_with_msg.message.id)
            except Exception as pin_error:
                logger.warning(f"Failed To Pin User Profile: Case {case_id} - {str(pin_error)[:50]}")

            return thread_with_msg.thread

        except Exception as e:
            logger.error("Failed To Create Case Thread", [
                ("User", f"{user.display_name} ({user.id})"),
                ("Case ID", case_id),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
            return None

    async def _update_profile_stats(self, user_id: int, case: dict) -> None:
        """
        Update the pinned profile message with current stats.

        Args:
            user_id: The user's Discord ID.
            case: The case data from database.
        """
        try:
            case_thread = await self._get_case_thread(case["thread_id"])
            if not case_thread:
                return

            profile_msg = None

            # Try to get stored message ID first
            if case.get("profile_message_id"):
                profile_msg = await safe_fetch_message(case_thread, case["profile_message_id"])

            # If not found, search pinned messages (for existing cases)
            if not profile_msg:
                try:
                    pinned = await case_thread.pins()
                    for msg in pinned:
                        if msg.embeds and msg.embeds[0].title == "📋 User Profile":
                            profile_msg = msg
                            # Store for future use
                            self.db.set_profile_message_id(user_id, msg.id)
                            break
                except Exception:
                    pass

            if not profile_msg:
                return

            # Get user info from the MAIN guild (not the forum's guild)
            main_guild_id = self.config.logging_guild_id
            guild = self.bot.get_guild(main_guild_id) if main_guild_id else case_thread.guild
            member = guild.get_member(user_id) if guild else None

            # Build updated embed
            embed = discord.Embed(
                title="📋 User Profile",
                color=EmbedColors.INFO,
                timestamp=datetime.now(NY_TZ),
            )

            if member:
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(name="Username", value=f"{member.name}", inline=True)
                embed.add_field(name="Display Name", value=f"{member.display_name}", inline=True)
            else:
                # User left server, try to fetch
                try:
                    user = await self.bot.fetch_user(user_id)
                    embed.set_thumbnail(url=user.display_avatar.url)
                    embed.add_field(name="Username", value=f"{user.name}", inline=True)
                    embed.add_field(name="Display Name", value=f"⚠️ Left Server", inline=True)
                except discord.NotFound:
                    embed.add_field(name="Username", value=f"Unknown", inline=True)
                    embed.add_field(name="Display Name", value=f"⚠️ User Not Found", inline=True)

            embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)

            # Stats section
            mute_count = case.get("mute_count", 0)
            ban_count = case.get("ban_count", 0)

            embed.add_field(name="Total Mutes", value=f"`{mute_count}`", inline=True)
            embed.add_field(name="Total Bans", value=f"`{ban_count}`", inline=True)

            # Last action
            last_mute = case.get("last_mute_at")
            last_ban = case.get("last_ban_at")
            if last_mute or last_ban:
                last_action = max(filter(None, [last_mute, last_ban]))
                embed.add_field(
                    name="Last Action",
                    value=f"<t:{int(last_action)}:R>",
                    inline=True,
                )

            # Warning for repeat offenders
            if mute_count >= 3 or ban_count >= 2:
                warnings = []
                if mute_count >= 3:
                    warnings.append(f"{mute_count} mutes")
                if ban_count >= 2:
                    warnings.append(f"{ban_count} bans")
                embed.add_field(
                    name="⚠️ Repeat Offender",
                    value=f"{', '.join(warnings)}",
                    inline=False,
                )

            # Previous names (if any)
            previous_names = self.db.get_previous_names(user_id, limit=3)
            if previous_names:
                names_str = ", ".join(f"`{name}`" for name in previous_names)
                embed.add_field(name="Previous Names", value=names_str, inline=False)

            set_footer(embed)

            # Edit the message with retry
            await safe_edit(profile_msg, embed=embed)

        except Exception as e:
            logger.warning(f"Failed to update profile stats: {str(e)[:50]}")

    # =========================================================================
    # Embed Builders
    # =========================================================================

    def _build_mute_embed(
        self,
        user: discord.Member,
        moderator: discord.Member,
        duration: str,
        reason: Optional[str] = None,
        mute_count: int = 1,
        is_extension: bool = False,
        evidence: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> discord.Embed:
        """
        Build a mute action embed.

        Args:
            user: The user being muted.
            moderator: The moderator who issued the mute.
            duration: Duration display string.
            reason: Optional reason for the mute.
            mute_count: The mute number for this user.
            is_extension: Whether this is a mute extension.
            evidence: Optional evidence link or description.
            expires_at: Optional expiry datetime for non-permanent mutes.

        Returns:
            Discord Embed for the mute action.
        """
        if is_extension:
            title = "🔇 Mute Extended"
        elif mute_count > 1:
            title = f"🔇 User Muted (Mute #{mute_count})"
        else:
            title = "🔇 User Muted"

        embed = discord.Embed(
            title=title,
            color=EmbedColors.ERROR,
            timestamp=datetime.now(NY_TZ),
        )
        embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Muted By", value=f"`{moderator.display_name}`", inline=True)
        embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

        # Expires field (for non-permanent mutes)
        if expires_at:
            embed.add_field(name="Expires", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True)
        else:
            embed.add_field(name="Expires", value="`Never`", inline=True)

        # Account Age with warning for new accounts
        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
        account_age_days = (now - created_at).days
        age_str = self._format_age(created_at, now)

        if account_age_days < 7:
            embed.add_field(name="Account Age", value=f"`{age_str}` ⚠️", inline=True)
        elif account_age_days < 30:
            embed.add_field(name="Account Age", value=f"`{age_str}` ⚡", inline=True)
        else:
            embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

        # Previous Mutes count
        previous_mutes = mute_count - 1 if mute_count > 1 else 0
        embed.add_field(name="Previous Mutes", value=f"`{previous_mutes}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        # Evidence: link to the evidence message in the case thread
        if evidence:
            embed.add_field(name="Evidence", value=f"[View Evidence]({evidence})", inline=False)

        set_footer(embed)
        return embed

    def _build_timeout_embed(
        self,
        user: discord.Member,
        mod_name: str,
        duration: str,
        until: datetime,
        reason: Optional[str] = None,
        mute_count: int = 1,
        moderator: Optional[discord.Member] = None,
    ) -> discord.Embed:
        """
        Build a timeout action embed.

        Args:
            user: The user being timed out.
            mod_name: Display name of the moderator.
            duration: Duration display string.
            until: When the timeout expires.
            reason: Optional reason for the timeout.
            mute_count: The mute number for this user.
            moderator: Optional moderator member object for author icon.

        Returns:
            Discord Embed for the timeout action.
        """
        if mute_count > 1:
            title = f"⏰ User Timed Out (Mute #{mute_count})"
        else:
            title = "⏰ User Timed Out"

        embed = discord.Embed(
            title=title,
            color=EmbedColors.WARNING,
            timestamp=datetime.now(NY_TZ),
        )
        if moderator:
            embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Timed Out By", value=f"`{mod_name}`", inline=True)
        embed.add_field(name="Duration", value=f"`{duration}`", inline=True)
        embed.add_field(name="Expires", value=f"<t:{int(until.timestamp())}:R>", inline=True)

        # Account Age with warning for new accounts
        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
        account_age_days = (now - created_at).days
        age_str = self._format_age(created_at, now)

        if account_age_days < 7:
            embed.add_field(name="Account Age", value=f"`{age_str}` ⚠️", inline=True)
        elif account_age_days < 30:
            embed.add_field(name="Account Age", value=f"`{age_str}` ⚡", inline=True)
        else:
            embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        set_footer(embed)
        return embed

    def _build_unmute_embed(
        self,
        moderator: discord.Member,
        reason: Optional[str] = None,
        user_avatar_url: Optional[str] = None,
        time_served: Optional[str] = None,
        original_duration: Optional[str] = None,
        original_moderator_name: Optional[str] = None,
    ) -> discord.Embed:
        """
        Build an unmute action embed.

        Args:
            moderator: The moderator who issued the unmute.
            reason: Optional reason for the unmute.
            user_avatar_url: Avatar URL of the unmuted user.
            time_served: How long the user was muted for.
            original_duration: Original mute duration.
            original_moderator_name: Name of the mod who issued the mute.

        Returns:
            Discord Embed for the unmute action.
        """
        embed = discord.Embed(
            title="🔊 User Unmuted",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )
        embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)
        embed.add_field(name="Unmuted By", value=f"`{moderator.display_name}`", inline=True)

        # Time served (how long they were muted)
        if time_served:
            embed.add_field(name="Was Muted For", value=f"`{time_served}`", inline=True)

        # Original duration
        if original_duration:
            embed.add_field(name="Original Duration", value=f"`{original_duration}`", inline=True)

        # Originally muted by
        if original_moderator_name:
            embed.add_field(name="Originally Muted By", value=f"`{original_moderator_name}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        set_footer(embed)
        return embed

    def _build_expired_embed(
        self,
        user_avatar_url: Optional[str] = None,
    ) -> discord.Embed:
        """
        Build a mute expired (auto-unmute) embed.

        Args:
            user_avatar_url: Avatar URL of the user whose mute expired.

        Returns:
            Discord Embed for the expiry.
        """
        embed = discord.Embed(
            title="⏰ Mute Expired (Auto-Unmute)",
            color=EmbedColors.INFO,
            timestamp=datetime.now(NY_TZ),
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)

        set_footer(embed)
        return embed

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _parse_duration_to_seconds(self, duration: str) -> Optional[int]:
        """
        Parse duration string to seconds.

        Supports formats like: 1h, 30m, 1d, 2d12h, permanent, perm, forever

        Args:
            duration: Duration string.

        Returns:
            Total seconds, or None for permanent/invalid durations.
        """
        if not duration:
            return None

        duration_lower = duration.lower().strip()

        # Permanent durations
        if duration_lower in ("permanent", "perm", "forever", "indefinite"):
            return None

        total_seconds = 0
        import re

        # Match patterns like 1d, 2h, 30m, 15s
        pattern = r"(\d+)\s*(d|h|m|s)"
        matches = re.findall(pattern, duration_lower)

        if not matches:
            return None

        multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}

        for value, unit in matches:
            total_seconds += int(value) * multipliers.get(unit, 0)

        return total_seconds if total_seconds > 0 else None

    def _format_age(self, start: datetime, end: datetime) -> str:
        """
        Format age as years, months, and days.

        Args:
            start: Start datetime.
            end: End datetime.

        Returns:
            Formatted string like "1y 6m 15d".
        """
        total_days = (end - start).days

        years = total_days // 365
        remaining_days = total_days % 365
        months = remaining_days // 30
        days = remaining_days % 30

        parts = []
        if years > 0:
            parts.append(f"{years}y")
        if months > 0:
            parts.append(f"{months}m")
        if days > 0 or not parts:
            parts.append(f"{days}d")

        return " ".join(parts)

    # =========================================================================
    # Pending Reason Handling
    # =========================================================================

    async def handle_reason_reply(
        self,
        message: "discord.Message",
    ) -> bool:
        """
        Handle a reply message that might be a pending reason response.

        Args:
            message: The reply message from the moderator.

        Returns:
            True if the reason was successfully applied, False otherwise.
        """
        # Must be a reply
        if not message.reference or not message.reference.message_id:
            return False

        # Check if this thread has a pending reason for this moderator
        pending = self.db.get_pending_reason_by_thread(message.channel.id, message.author.id)
        if not pending:
            return False

        # Verify the reply is to the warning message
        if message.reference.message_id != pending["warning_message_id"]:
            return False

        # Get the reason from the message content (limit to 500 chars)
        reason = message.content.strip()[:500]
        action_type = pending["action_type"]

        # Check for attachments (images/videos)
        attachment_url = None
        if message.attachments:
            # Get the first image/video attachment
            for att in message.attachments:
                if att.content_type and (att.content_type.startswith("image/") or att.content_type.startswith("video/")):
                    attachment_url = att.url
                    break

        # For mute/ban: require attachment (text is optional)
        # For unmute/unban: require text only
        if action_type in ("mute", "extension", "ban"):
            if not attachment_url:
                # No attachment provided - send reminder and don't process
                try:
                    reminder = await message.channel.send(
                        f"{message.author.mention} An attachment (screenshot/video) is required. Please reply again with evidence attached.",
                        delete_after=10,
                    )
                except discord.HTTPException:
                    pass
                return False
        else:
            # unmute/unban - just need text
            if not reason:
                return False

        try:
            thread = message.channel
            embed_message = await safe_fetch_message(thread, pending["embed_message_id"])

            if not embed_message or not embed_message.embeds:
                return False

            # Update the embed with the reason and/or attachment
            embed = embed_message.embeds[0]

            # Find and update the Reason field, or add it (if reason provided)
            if reason:
                reason_field_index = None
                for i, field in enumerate(embed.fields):
                    if field.name == "Reason":
                        reason_field_index = i
                        break

                if reason_field_index is not None:
                    embed.set_field_at(
                        reason_field_index,
                        name="Reason",
                        value=f"`{reason}`",
                        inline=False,
                    )
                else:
                    embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

            # Send attachment as separate message first to preserve it permanently
            # Then add link to embed
            evidence_message_url = None
            if attachment_url:
                evidence_msg = await safe_send(thread, f"📎 **Evidence:**\n{attachment_url}")
                if evidence_msg:
                    evidence_message_url = evidence_msg.jump_url
                    embed.add_field(name="Evidence", value=f"[View Evidence]({evidence_message_url})", inline=False)

            # Preserve the view (buttons) when editing
            view = None
            if embed_message.components:
                # Recreate the view for this message
                view = CaseLogView(
                    user_id=pending["target_user_id"],
                    guild_id=thread.guild.id if thread.guild else None,
                    case_thread_id=thread.id,
                    is_mute_embed=(action_type in ("mute", "extension")),
                )

            if view:
                await safe_edit(embed_message, embed=embed, view=view)
            else:
                await safe_edit(embed_message, embed=embed)

            # Delete the warning message and mod's reply silently
            for msg_id in [pending["warning_message_id"], message.id]:
                msg = await safe_fetch_message(thread, msg_id)
                if msg:
                    await safe_delete(msg)

            # Send confirmation message with timestamp
            timestamp = int(datetime.now(NY_TZ).timestamp())
            confirmation_parts = []
            if evidence_message_url:
                confirmation_parts.append("Evidence uploaded")
            if reason:
                confirmation_parts.append("reason added")
            confirmation_text = " and ".join(confirmation_parts) if confirmation_parts else "Updated"

            try:
                await thread.send(
                    f"✅ {confirmation_text} successfully at <t:{timestamp}:T>",
                    delete_after=10,
                )
            except discord.HTTPException:
                pass

            # Remove the pending reason from database
            self.db.delete_pending_reason(pending["id"])

            # Log success
            logger.tree("Case Log: Reason Updated", [
                ("Thread ID", str(thread.id)),
                ("Moderator", f"{message.author} ({message.author.id})"),
                ("Action", action_type),
                ("Reason", reason[:50] if reason else "N/A"),
                ("Evidence", "Uploaded" if evidence_message_url else "N/A"),
            ], emoji="✅")

            return True

        except Exception as e:
            logger.error("Case Log: Failed To Update Reason", [
                ("Thread ID", str(message.channel.id)),
                ("Error", str(e)[:100]),
            ])
            return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CaseLogService"]
