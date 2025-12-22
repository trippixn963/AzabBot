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
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, Tuple

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.views import CASE_EMOJI, MESSAGE_EMOJI, DownloadButton

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# View Classes
# =============================================================================

class CaseLogView(discord.ui.View):
    """View with Case button (if user has case), jump-to-message, and download avatar buttons."""

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        message_url: Optional[str] = None,
        case_thread_id: Optional[int] = None,
    ):
        super().__init__(timeout=None)

        # Button 1: Case link (if user has an open case)
        if case_thread_id:
            case_url = f"https://discord.com/channels/{guild_id}/{case_thread_id}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))

        # Button 2: Jump to message (if provided)
        if message_url:
            self.add_item(discord.ui.Button(
                label="Message",
                url=message_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
            ))

        # Button 3: Download PFP (persistent button)
        self.add_item(DownloadButton(user_id))


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

        logger.info("Pending Reason Scheduler Stopped")

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

                await thread.send(
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

        # Cache miss or expired - fetch forum
        try:
            channel = self.bot.get_channel(self.config.case_log_forum_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.config.case_log_forum_id)
            if isinstance(channel, discord.ForumChannel):
                self._forum = channel
                self._forum_cache_time = now
        except Exception as e:
            logger.warning(f"Failed To Get Case Log Forum: {self.config.case_log_forum_id} - {str(e)[:50]}")
            return None

        return self._forum

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
                logger.debug(f"Thread Cache HIT: {thread_id}")
                return cached_thread
            else:
                # Cache expired, remove it
                logger.debug(f"Thread Cache EXPIRED: {thread_id}")
                del self._thread_cache[thread_id]
        else:
            logger.debug(f"Thread Cache MISS: {thread_id}")

        # Cache miss - fetch thread
        try:
            thread = self.bot.get_channel(thread_id)
            fetch_method = "get_channel" if thread else "fetch_channel"
            if thread is None:
                thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                # Cache the result
                self._thread_cache[thread_id] = (thread, now)
                logger.debug(f"Thread Fetched via {fetch_method}: {thread_id} -> {thread.name}")
                # Cleanup old cache entries (keep max 100)
                if len(self._thread_cache) > 100:
                    oldest = min(self._thread_cache.keys(), key=lambda k: self._thread_cache[k][1])
                    del self._thread_cache[oldest]
                return thread
            else:
                logger.warning(f"Channel {thread_id} is not a Thread: {type(thread)}")
        except discord.NotFound:
            logger.warning(f"Case Thread Not Found: {thread_id}")
        except Exception as e:
            logger.error("Case Thread Fetch Failed", [
                ("Thread ID", str(thread_id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
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
            logger.debug(f"log_mute: Service disabled, skipping for {user.id}")
            return None

        try:
            logger.debug(f"log_mute: Getting/creating case for {user.display_name} ({user.id})")
            case = await self._get_or_create_case(user)
            logger.debug(f"log_mute: Got case {case['case_id']}, thread_id={case['thread_id']}, just_created={case.get('just_created', False)}")

            logger.debug(f"log_mute: Fetching thread {case['thread_id']}")
            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                logger.warning(f"log_mute: Thread {case['thread_id']} not found, returning early")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            # Determine mute count (don't increment for extensions)
            if case.get("just_created"):
                mute_count = 1
            elif is_extension:
                # Get current count without incrementing
                case_data = self.db.get_case_log(user.id)
                mute_count = case_data["mute_count"] if case_data else 1
            else:
                mute_count = self.db.increment_mute_count(user.id)

            # Build and send mute embed with jump button and download
            logger.debug(f"log_mute: Building mute embed for {user.id}")
            embed = self._build_mute_embed(user, moderator, duration, reason, mute_count, is_extension, evidence)
            view = CaseLogView(
                user_id=user.id,
                guild_id=user.guild.id,
                message_url=source_message_url,
                case_thread_id=case["thread_id"],
            )
            logger.debug(f"log_mute: Sending mute embed to thread {case_thread.id}")
            embed_message = await case_thread.send(embed=embed, view=view)
            logger.debug(f"log_mute: Mute embed sent, msg_id={embed_message.id}")

            # If no reason provided, ping moderator and track pending reason
            if not reason:
                action_type = "extension" if is_extension else "mute"
                logger.debug(f"log_mute: No reason provided, sending warning to mod {moderator.id}")
                warning_message = await case_thread.send(
                    f"⚠️ {moderator.mention} No reason was provided for this {action_type}.\n\n"
                    f"**Reply to this message** with:\n"
                    f"• A reason **and** an attachment (screenshot/video), OR\n"
                    f"• Just an attachment\n\n"
                    f"You have **1 hour** or the owner will be notified.\n"
                    f"_Only replies from you will be accepted._"
                )
                logger.debug(f"log_mute: Warning sent, msg_id={warning_message.id}")
                # Track pending reason in database
                self.db.create_pending_reason(
                    thread_id=case_thread.id,
                    warning_message_id=warning_message.id,
                    embed_message_id=embed_message.id,
                    moderator_id=moderator.id,
                    target_user_id=user.id,
                    action_type=action_type,
                )
                logger.debug(f"log_mute: Pending reason tracked in DB")

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
                    await case_thread.send(embed=alert_embed)

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

            # Update the profile stats
            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                await self._update_profile_stats(user.id, updated_case)

            logger.debug(f"log_mute: Completed successfully for {user.id}, case={case['case_id']}")
            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute", [
                ("User ID", str(user.id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:200]),
            ])
            import traceback
            logger.debug(f"log_mute traceback: {traceback.format_exc()}")
            return None

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

            # Update last unmute timestamp
            self.db.update_last_unmute(user_id)

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = self._build_unmute_embed(moderator, reason, user_avatar_url)
                view = CaseLogView(
                    user_id=user_id,
                    guild_id=moderator.guild.id,
                    message_url=source_message_url,
                    case_thread_id=case["thread_id"],
                )
                embed_message = await case_thread.send(embed=embed, view=view)

                # If no reason provided, ping moderator and track pending reason
                if not reason:
                    warning_message = await case_thread.send(
                        f"⚠️ {moderator.mention} No reason was provided for this unmute.\n\n"
                        f"**Reply to this message** with the reason within **1 hour** or the owner will be notified.\n"
                        f"_Only replies from you will be accepted._"
                    )
                    # Track pending reason in database
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

                # Update the profile stats
                updated_case = self.db.get_case_log(user_id)
                if updated_case:
                    await self._update_profile_stats(user_id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Unmute", [
                ("User ID", str(user_id)),
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
            logger.debug(f"log_ban: Service disabled, skipping for {user.id}")
            return None

        try:
            logger.debug(f"log_ban: Getting/creating case for {user.display_name} ({user.id})")
            case = await self._get_or_create_case(user)
            logger.debug(f"log_ban: Got case {case['case_id']}, thread_id={case['thread_id']}")

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                logger.warning(f"log_ban: Thread {case['thread_id']} not found, returning early")
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            now = datetime.now(NY_TZ)
            logger.debug(f"log_ban: Building ban embed for {user.id}")

            embed = discord.Embed(
                title="🔨 User Banned",
                color=EmbedColors.ERROR,
                timestamp=now,
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Moderator", value=f"{moderator.mention}\n`{moderator.display_name}`", inline=True)

            if reason:
                embed.add_field(name="Reason", value=f"```{reason}```", inline=False)
            else:
                embed.add_field(name="Reason", value="```No reason provided```", inline=False)

            if evidence:
                embed.add_field(name="Evidence", value=evidence, inline=False)

            embed.set_footer(text=f"Ban • ID: {user.id}")

            view = CaseLogView(
                user_id=user.id,
                guild_id=user.guild.id,
                message_url=source_message_url,
                case_thread_id=case["thread_id"],
            )
            logger.debug(f"log_ban: Sending ban embed to thread {case_thread.id}")
            embed_message = await case_thread.send(embed=embed, view=view)
            logger.debug(f"log_ban: Ban embed sent, msg_id={embed_message.id}")

            # If no reason provided, ping moderator and track pending reason
            if not reason:
                logger.debug(f"log_ban: No reason provided, sending warning to mod {moderator.id}")
                warning_message = await case_thread.send(
                    f"⚠️ {moderator.mention} No reason was provided for this ban.\n\n"
                    f"**Reply to this message** with:\n"
                    f"• A reason **and** an attachment (screenshot/video), OR\n"
                    f"• Just an attachment\n\n"
                    f"You have **1 hour** or the owner will be notified.\n"
                    f"_Only replies from you will be accepted._"
                )
                logger.debug(f"log_ban: Warning sent, msg_id={warning_message.id}")
                # Track pending reason in database
                self.db.create_pending_reason(
                    thread_id=case_thread.id,
                    warning_message_id=warning_message.id,
                    embed_message_id=embed_message.id,
                    moderator_id=moderator.id,
                    target_user_id=user.id,
                    action_type="ban",
                )
                logger.debug(f"log_ban: Pending reason tracked in DB")

            logger.tree("Case Log: Ban Logged", [
                ("User", f"{user} ({user.id})"),
                ("Case ID", case['case_id']),
                ("Banned By", f"{moderator.display_name}"),
            ], emoji="🔨")

            # Update the profile stats
            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                await self._update_profile_stats(user.id, updated_case)

            logger.debug(f"log_ban: Completed successfully for {user.id}, case={case['case_id']}")
            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Ban", [
                ("User ID", str(user.id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:200]),
            ])
            import traceback
            logger.debug(f"log_ban traceback: {traceback.format_exc()}")
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

            case_thread = await self._get_case_thread(case["thread_id"])

            if case_thread:
                now = datetime.now(NY_TZ)

                embed = discord.Embed(
                    title="🔓 User Unbanned",
                    color=EmbedColors.SUCCESS,
                    timestamp=now,
                )
                embed.add_field(name="Moderator", value=f"{moderator.mention}\n`{moderator.display_name}`", inline=True)

                if reason:
                    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

                embed.set_footer(text=f"Unban • ID: {user_id}")

                view = CaseLogView(
                    user_id=user_id,
                    guild_id=moderator.guild.id,
                    message_url=source_message_url,
                    case_thread_id=case["thread_id"],
                )
                embed_message = await case_thread.send(embed=embed, view=view)

                # If no reason provided, ping moderator and track pending reason
                if not reason:
                    warning_message = await case_thread.send(
                        f"⚠️ {moderator.mention} No reason was provided for this unban.\n\n"
                        f"**Reply to this message** with the reason within **1 hour** or the owner will be notified.\n"
                        f"_Only replies from you will be accepted._"
                    )
                    # Track pending reason in database
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

                # Update the profile stats
                updated_case = self.db.get_case_log(user_id)
                if updated_case:
                    await self._update_profile_stats(user_id, updated_case)

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
                await case_thread.send(embed=embed, view=view)

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
    ) -> None:
        """
        Log when a muted user leaves the server.

        Args:
            user_id: The user who left.
            display_name: Display name of the user.
            muted_at: Timestamp when the user was muted.
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
                    title="🚪 Left Server While Muted",
                    description="User left the server with an active mute.",
                    color=EmbedColors.WARNING,
                    timestamp=now,
                )

                # Calculate time since muted
                time_since_mute = now.timestamp() - muted_at
                duration_str = self._format_duration_precise(time_since_mute)
                embed.add_field(
                    name="Time After Mute",
                    value=f"`{duration_str}`",
                    inline=True,
                )

                embed.set_footer(text=f"Leave • ID: {user_id}")
                await case_thread.send(embed=embed)

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

                view = CaseLogView(
                    user_id=member.id,
                    guild_id=member.guild.id,
                    case_thread_id=case["thread_id"],
                )
                await case_thread.send(embed=embed, view=view)

                # Ping all moderators who muted this user
                if moderator_ids:
                    pings = " ".join(f"<@{mod_id}>" for mod_id in moderator_ids)
                    await case_thread.send(f"🔔 {pings}")

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
    ) -> None:
        """
        Log when a muted user attempts to join voice and gets timed out.

        Args:
            user_id: The user's Discord ID.
            display_name: The user's display name.
            channel_name: The voice channel they attempted to join.
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
                await case_thread.send(embed=embed)

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
    ) -> dict:
        """
        Get existing case or create new one with forum thread.

        Args:
            user: The user to get/create case for.

        Returns:
            Dict with case info, includes 'just_created' flag if new.
        """
        logger.debug(f"_get_or_create_case: Checking DB for user {user.id}")
        case = self.db.get_case_log(user.id)
        if case:
            logger.debug(f"_get_or_create_case: Found existing case {case['case_id']} for user {user.id}")
            return case  # Existing case

        # Create new case
        logger.debug(f"_get_or_create_case: No existing case, creating new for user {user.id}")
        case_id = self.db.get_next_case_id()
        logger.debug(f"_get_or_create_case: Generated case_id={case_id}")

        thread = await self._create_case_thread(user, case_id)

        if thread:
            logger.debug(f"_get_or_create_case: Thread created successfully: {thread.id} ({thread.name})")
            self.db.create_case_log(user.id, case_id, thread.id)
            # Cache the thread immediately so we don't need to fetch it again
            self._thread_cache[thread.id] = (thread, datetime.now(NY_TZ))
            logger.debug(f"_get_or_create_case: Thread {thread.id} cached, returning case")
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
        logger.debug(f"_create_case_thread: Starting for user {user.id}, case_id={case_id}")
        forum = await self._get_forum()
        if not forum:
            logger.warning(f"_create_case_thread: Forum not found, cannot create thread")
            return None
        logger.debug(f"_create_case_thread: Got forum {forum.id} ({forum.name})")

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

        set_footer(user_embed)

        # Create thread with user profile only
        thread_name = f"[{case_id}] | {user.display_name}"
        logger.debug(f"_create_case_thread: Creating thread '{thread_name[:100]}'")

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],  # Discord limit
                embed=user_embed,
            )
            logger.debug(f"_create_case_thread: Thread created: {thread_with_msg.thread.id}")

            # Pin the first message (user profile) and store its ID
            try:
                if thread_with_msg.message:
                    await thread_with_msg.message.pin()
                    # Store the message ID for future updates
                    self.db.set_profile_message_id(user.id, thread_with_msg.message.id)
                    logger.debug(f"_create_case_thread: Profile pinned, msg_id={thread_with_msg.message.id}")
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
                try:
                    profile_msg = await case_thread.fetch_message(case["profile_message_id"])
                except discord.NotFound:
                    pass

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

            set_footer(embed)

            # Edit the message
            await profile_msg.edit(embed=embed)

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
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Muted By", value=f"`{moderator.display_name}`", inline=True)
        embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        if evidence:
            embed.add_field(name="Evidence", value=evidence, inline=False)

        set_footer(embed)
        return embed

    def _build_unmute_embed(
        self,
        moderator: discord.Member,
        reason: Optional[str] = None,
        user_avatar_url: Optional[str] = None,
    ) -> discord.Embed:
        """
        Build an unmute action embed.

        Args:
            moderator: The moderator who issued the unmute.
            reason: Optional reason for the unmute.
            user_avatar_url: Avatar URL of the unmuted user.

        Returns:
            Discord Embed for the unmute action.
        """
        embed = discord.Embed(
            title="🔊 User Unmuted",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)
        embed.add_field(name="Unmuted By", value=f"{moderator.mention}", inline=True)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

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
            embed_message = await thread.fetch_message(pending["embed_message_id"])

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

            # Add attachment as image (for mute/ban)
            if attachment_url:
                embed.set_image(url=attachment_url)

            await embed_message.edit(embed=embed)

            # Delete the warning message and mod's reply silently
            for msg_id in [pending["warning_message_id"], message.id]:
                try:
                    msg = await thread.fetch_message(msg_id)
                    await msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

            # Remove the pending reason from database
            self.db.delete_pending_reason(pending["id"])

            # Log success
            logger.tree("Case Log: Reason Updated", [
                ("Thread ID", str(thread.id)),
                ("Moderator", f"{message.author} ({message.author.id})"),
                ("Action", action_type),
                ("Reason", reason[:50] if reason else "N/A"),
                ("Has Attachment", "Yes" if attachment_url else "No"),
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
