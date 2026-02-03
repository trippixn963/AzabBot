"""
AzabBot - Content Moderation Service
====================================

AI-powered content moderation for detecting religion discussions.

Author: John Hamwi
Server: discord.gg/syria
"""

import asyncio
import hashlib
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.constants import (
    RELIGION_OFFENSE_WINDOW,
    RELIGION_OFFENSE_THRESHOLD,
    RELIGION_AUTO_MUTE_MINUTES,
    RELIGION_WARNING_DELETE_AFTER,
    RELIGION_MUTE_MSG_DELETE_AFTER,
)
from src.core.logger import logger
from src.utils.async_utils import create_safe_task
from src.utils.footer import set_footer
from src.utils.snipe_blocker import block_from_snipe

from .classifier import ContentClassifier, ClassificationResult
from .constants import (
    CLASSIFICATION_CACHE_SIZE,
    CLASSIFICATION_CACHE_TTL,
    CONFIDENCE_THRESHOLD_ALERT,
    CONFIDENCE_THRESHOLD_DELETE,
    MAX_API_CALLS_PER_MINUTE,
    MIN_MESSAGE_LENGTH,
    USER_CHECK_COOLDOWN,
    VIOLATION_EMOJI,
    VIOLATION_TYPE,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

CLEANUP_INTERVAL = 300  # 5 minutes - cleanup old cooldowns/timestamps
MAX_COOLDOWN_ENTRIES = 10000  # Max user cooldown entries before forced cleanup


# =============================================================================
# Service Class
# =============================================================================

class ContentModerationService:
    """
    AI-powered content moderation service.

    Features:
        - OpenAI classification for religion discussion detection
        - Configurable confidence thresholds
        - Rate limiting to control API costs
        - Caching to avoid duplicate checks
        - Auto-delete for high-confidence violations
        - Mod alerts for medium-confidence detections
        - Background cleanup task for memory management
        - Snipe prevention for moderation-deleted messages

    Attributes:
        bot: The bot instance.
        config: Bot configuration.
        classifier: OpenAI content classifier.
        enabled: Whether the service is enabled.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the content moderation service.

        Args:
            bot: The bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.classifier = ContentClassifier()

        # Rate limiting (timestamps of recent API calls)
        self._api_calls: List[datetime] = []
        self._api_lock = asyncio.Lock()

        # User cooldowns (user_id -> last check time)
        self._user_cooldowns: Dict[int, datetime] = {}
        self._cooldown_lock = asyncio.Lock()

        # Classification cache (content_hash -> (result, timestamp))
        self._cache: OrderedDict[str, Tuple[ClassificationResult, datetime]] = OrderedDict()
        self._cache_lock = asyncio.Lock()

        # Offense tracking for auto-mute (user_id -> list of offense timestamps)
        self._offense_history: Dict[int, List[datetime]] = {}
        self._offense_lock = asyncio.Lock()

        # Exempt channels and roles
        self._exempt_channels: Set[int] = set()
        self._exempt_roles: Set[int] = set()
        self._load_exemptions()

        # Start background cleanup task
        if self.enabled:
            self._start_cleanup_task()

        # Log initialization
        if self.enabled:
            logger.tree("Content Moderation Service Loaded", [
                ("Classifier", "OpenAI GPT-4o-mini"),
                ("Delete Threshold", f"{CONFIDENCE_THRESHOLD_DELETE:.0%}"),
                ("Alert Threshold", f"{CONFIDENCE_THRESHOLD_ALERT:.0%}"),
                ("Rate Limit", f"{MAX_API_CALLS_PER_MINUTE}/min"),
                ("Cache Size", str(CLASSIFICATION_CACHE_SIZE)),
                ("Cache TTL", f"{CLASSIFICATION_CACHE_TTL}s"),
            ], emoji=VIOLATION_EMOJI)
        else:
            logger.info("Content Moderation Service Disabled (no API key)")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if service is enabled."""
        return self.classifier.enabled

    # =========================================================================
    # Initialization Helpers
    # =========================================================================

    def _load_exemptions(self) -> None:
        """Load exempt channels and roles from config."""
        # Exempt mod/log channels
        if self.config.mod_logs_forum_id:
            self._exempt_channels.add(self.config.mod_logs_forum_id)
        if self.config.server_logs_forum_id:
            self._exempt_channels.add(self.config.server_logs_forum_id)
        if self.config.case_log_forum_id:
            self._exempt_channels.add(self.config.case_log_forum_id)
        if self.config.modmail_forum_id:
            self._exempt_channels.add(self.config.modmail_forum_id)
        if self.config.appeal_forum_id:
            self._exempt_channels.add(self.config.appeal_forum_id)

        # Exempt mod role
        if self.config.moderation_role_id:
            self._exempt_roles.add(self.config.moderation_role_id)

        logger.debug(f"Content moderation exemptions loaded: {len(self._exempt_channels)} channels, {len(self._exempt_roles)} roles")

    def _start_cleanup_task(self) -> None:
        """Start background cleanup task."""
        create_safe_task(self._cleanup_loop(), "Content Moderation Cleanup")

    # =========================================================================
    # Background Tasks
    # =========================================================================

    async def _cleanup_loop(self) -> None:
        """Periodically clean up old cooldowns and cache entries."""
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            try:
                await self._cleanup_old_entries()
            except Exception as e:
                logger.warning("Content Moderation Cleanup Error", [
                    ("Error", str(e)[:50]),
                    ("Type", type(e).__name__),
                ])

    async def _cleanup_old_entries(self) -> None:
        """Clean up expired cooldowns and cache entries."""
        now = datetime.now(NY_TZ)
        cleaned_cooldowns = 0
        cleaned_cache = 0

        # Clean user cooldowns
        async with self._cooldown_lock:
            cooldown_cutoff = now - timedelta(seconds=USER_CHECK_COOLDOWN * 2)
            expired_users = [
                user_id for user_id, timestamp in self._user_cooldowns.items()
                if timestamp < cooldown_cutoff
            ]
            for user_id in expired_users:
                try:
                    del self._user_cooldowns[user_id]
                    cleaned_cooldowns += 1
                except KeyError:
                    pass

        # Clean classification cache
        async with self._cache_lock:
            cache_cutoff = now - timedelta(seconds=CLASSIFICATION_CACHE_TTL)
            expired_hashes = [
                content_hash for content_hash, (_, timestamp) in self._cache.items()
                if timestamp < cache_cutoff
            ]
            for content_hash in expired_hashes:
                try:
                    del self._cache[content_hash]
                    cleaned_cache += 1
                except KeyError:
                    pass

        # Clean old API call timestamps
        async with self._api_lock:
            api_cutoff = now - timedelta(minutes=2)
            self._api_calls = [t for t in self._api_calls if t > api_cutoff]

        # Clean old offense history
        cleaned_offenses = 0
        async with self._offense_lock:
            offense_cutoff = now - timedelta(seconds=RELIGION_OFFENSE_WINDOW)
            users_to_remove = []
            for user_id, timestamps in self._offense_history.items():
                # Remove old timestamps
                self._offense_history[user_id] = [t for t in timestamps if t > offense_cutoff]
                # Mark for removal if no recent offenses
                if not self._offense_history[user_id]:
                    users_to_remove.append(user_id)
            for user_id in users_to_remove:
                try:
                    del self._offense_history[user_id]
                    cleaned_offenses += 1
                except KeyError:
                    pass

        if cleaned_cooldowns > 0 or cleaned_cache > 0 or cleaned_offenses > 0:
            logger.debug(f"Content moderation cleanup: {cleaned_cooldowns} cooldowns, {cleaned_cache} cache, {cleaned_offenses} offense records")

    # =========================================================================
    # Exemption Checks
    # =========================================================================

    def _is_exempt(self, message: discord.Message) -> Tuple[bool, str]:
        """
        Check if message is exempt from moderation.

        Args:
            message: The message to check.

        Returns:
            Tuple of (is_exempt, reason).
        """
        # Bots are exempt
        if message.author.bot:
            return True, "bot"

        # Check channel exemptions
        channel_id = message.channel.id
        if channel_id in self._exempt_channels:
            return True, "exempt_channel"

        # Check if in exempt forum thread
        if isinstance(message.channel, discord.Thread):
            if message.channel.parent_id and message.channel.parent_id in self._exempt_channels:
                return True, "exempt_forum_thread"

        # Check role exemptions
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.id in self._exempt_roles:
                    return True, "exempt_role"
            # Admins exempt
            if message.author.guild_permissions.administrator:
                return True, "administrator"

        return False, ""

    # =========================================================================
    # Caching
    # =========================================================================

    def _hash_content(self, content: str) -> str:
        """
        Create hash of content for caching.

        Args:
            content: Message content to hash.

        Returns:
            MD5 hash of normalized content.
        """
        normalized = content.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    async def _get_cached_result(self, content_hash: str) -> Optional[ClassificationResult]:
        """
        Get cached classification result if valid.

        Args:
            content_hash: Hash of the content to look up.

        Returns:
            Cached ClassificationResult or None if not found/expired.
        """
        async with self._cache_lock:
            if content_hash not in self._cache:
                return None

            result, timestamp = self._cache[content_hash]
            if datetime.now(NY_TZ) - timestamp > timedelta(seconds=CLASSIFICATION_CACHE_TTL):
                # Expired
                try:
                    del self._cache[content_hash]
                except KeyError:
                    pass
                return None

            # Move to end (LRU)
            self._cache.move_to_end(content_hash)
            logger.debug(f"Cache hit for content hash {content_hash[:8]}")
            return result

    async def _cache_result(self, content_hash: str, result: ClassificationResult) -> None:
        """
        Cache classification result.

        Args:
            content_hash: Hash of the content.
            result: Classification result to cache.
        """
        async with self._cache_lock:
            # Evict oldest if at limit
            while len(self._cache) >= CLASSIFICATION_CACHE_SIZE:
                self._cache.popitem(last=False)

            self._cache[content_hash] = (result, datetime.now(NY_TZ))

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    async def _check_rate_limit(self) -> bool:
        """
        Check if we can make an API call.

        Returns:
            True if allowed, False if rate limited.
        """
        async with self._api_lock:
            now = datetime.now(NY_TZ)
            cutoff = now - timedelta(minutes=1)

            # Remove old entries
            self._api_calls = [t for t in self._api_calls if t > cutoff]

            if len(self._api_calls) >= MAX_API_CALLS_PER_MINUTE:
                return False

            self._api_calls.append(now)
            return True

    async def _check_user_cooldown(self, user_id: int) -> bool:
        """
        Check if user is on cooldown.

        Args:
            user_id: The user ID to check.

        Returns:
            True if NOT on cooldown (can check), False if on cooldown.
        """
        now = datetime.now(NY_TZ)

        async with self._cooldown_lock:
            last_check = self._user_cooldowns.get(user_id)

            if last_check and (now - last_check).total_seconds() < USER_CHECK_COOLDOWN:
                return False

            # Force cleanup if too many entries
            if len(self._user_cooldowns) >= MAX_COOLDOWN_ENTRIES:
                # Remove oldest half
                sorted_items = sorted(self._user_cooldowns.items(), key=lambda x: x[1])
                for uid, _ in sorted_items[:MAX_COOLDOWN_ENTRIES // 2]:
                    try:
                        del self._user_cooldowns[uid]
                    except KeyError:
                        pass
                logger.debug(f"Forced cooldown cleanup: removed {MAX_COOLDOWN_ENTRIES // 2} entries")

            self._user_cooldowns[user_id] = now
            return True

    # =========================================================================
    # Main Check Method
    # =========================================================================

    async def check_message(self, message: discord.Message) -> Optional[ClassificationResult]:
        """
        Check a message for content violations.

        Args:
            message: The message to check.

        Returns:
            ClassificationResult if checked, None if skipped.
        """
        if not self.enabled:
            return None

        # Skip exempt messages
        is_exempt, exempt_reason = self._is_exempt(message)
        if is_exempt:
            return None

        # Skip non-guild messages
        if not message.guild:
            return None

        # Skip mod server
        if self.config.mod_server_id and message.guild.id == self.config.mod_server_id:
            return None

        content = message.content or ""

        # Skip short messages
        if len(content) < MIN_MESSAGE_LENGTH:
            return None

        # Check user cooldown
        if not await self._check_user_cooldown(message.author.id):
            return None

        # Check cache
        content_hash = self._hash_content(content)
        cached = await self._get_cached_result(content_hash)
        if cached is not None:
            return cached

        # Check rate limit
        if not await self._check_rate_limit():
            logger.debug("Content moderation rate limited", [
                ("User", str(message.author.id)),
                ("Channel", str(message.channel.id)),
            ])
            return None

        # Classify
        result = await self.classifier.classify(content)

        # Cache result (even non-violations to avoid re-checking)
        await self._cache_result(content_hash, result)

        # Log classification
        if result.violation:
            logger.tree("Content Classification", [
                ("User", f"{message.author} ({message.author.id})"),
                ("Violation", "Yes"),
                ("Confidence", f"{result.confidence:.0%}"),
                ("Reason", result.reason[:50]),
            ], emoji="🔍")
        elif result.error:
            logger.debug(f"Classification error for user {message.author.id}: {result.error}")

        return result

    # =========================================================================
    # Violation Handling
    # =========================================================================

    async def handle_violation(
        self,
        message: discord.Message,
        result: ClassificationResult,
    ) -> None:
        """
        Handle a detected content violation.

        Args:
            message: The violating message.
            result: The classification result.
        """
        # High confidence: delete message and warn
        if result.confidence >= CONFIDENCE_THRESHOLD_DELETE:
            await self._handle_high_confidence(message, result)
        # Medium confidence: alert mods
        elif result.confidence >= CONFIDENCE_THRESHOLD_ALERT:
            await self._handle_medium_confidence(message, result)

    async def _handle_high_confidence(
        self,
        message: discord.Message,
        result: ClassificationResult,
    ) -> None:
        """
        Handle high-confidence violation (auto-delete + warn).

        Args:
            message: The violating message.
            result: The classification result.
        """
        user_str = f"{message.author} ({message.author.id})"
        channel_str = f"#{message.channel.name}" if hasattr(message.channel, "name") else str(message.channel.id)

        try:
            # Block from snipe cache BEFORE deleting
            await block_from_snipe(
                message.id,
                reason="Religion talk",
                user_id=message.author.id,
                channel_name=f"#{message.channel.name}" if hasattr(message.channel, "name") else None,
            )

            # Delete the message
            await message.delete()

            # Track offense and check for auto-mute
            user_id = message.author.id
            now = datetime.now(NY_TZ)
            offense_count = await self._record_offense(user_id, now)

            logger.tree("RELIGION TALK DELETED", [
                ("User", user_str),
                ("Channel", channel_str),
                ("Confidence", f"{result.confidence:.0%}"),
                ("Offense Count", f"{offense_count} in last hour"),
                ("Content", message.content[:50] + "..." if len(message.content) > 50 else message.content),
            ], emoji=VIOLATION_EMOJI)

            # Check if auto-mute threshold reached
            if offense_count >= RELIGION_OFFENSE_THRESHOLD:
                await self._auto_mute_user(message, offense_count)
            else:
                # Send simple warning to channel
                try:
                    warning_msg = (
                        f"{VIOLATION_EMOJI} {message.author.mention}, no religion talk.\n"
                        f"-# Repeated offenses will cause an auto mute"
                    )
                    await message.channel.send(warning_msg, delete_after=RELIGION_WARNING_DELETE_AFTER)
                    logger.debug(f"Warning sent to {channel_str}")
                except discord.HTTPException as e:
                    logger.warning("Failed to send warning", [
                        ("Channel", channel_str),
                        ("Error", str(e)[:50]),
                    ])

            # Try to DM the user
            await self._send_violation_dm(message, result)

            # Alert mods via logging service
            await self._send_mod_alert(message, result, deleted=True)

        except discord.NotFound:
            logger.debug(f"Message already deleted for user {message.author.id}")
        except discord.Forbidden:
            logger.warning("No Permission to Delete", [
                ("Channel", channel_str),
                ("User", user_str),
            ])
        except discord.HTTPException as e:
            logger.error("Failed to Handle Violation", [
                ("Error", str(e)[:50]),
                ("User", user_str),
            ])

    async def _handle_medium_confidence(
        self,
        message: discord.Message,
        result: ClassificationResult,
    ) -> None:
        """
        Handle medium-confidence violation (alert mods only).

        Args:
            message: The flagged message.
            result: The classification result.
        """
        user_str = f"{message.author} ({message.author.id})"
        channel_str = f"#{message.channel.name}" if hasattr(message.channel, "name") else str(message.channel.id)

        logger.tree("RELIGION TALK FLAGGED", [
            ("User", user_str),
            ("Channel", channel_str),
            ("Confidence", f"{result.confidence:.0%}"),
            ("Reason", result.reason[:50]),
            ("Action", "Alert mods for review"),
        ], emoji="🚩")

        # Alert mods for review
        await self._send_mod_alert(message, result, deleted=False)

    async def _record_offense(self, user_id: int, timestamp: datetime) -> int:
        """
        Record an offense and return count of recent offenses.

        Args:
            user_id: The user's ID.
            timestamp: When the offense occurred.

        Returns:
            Number of offenses within the offense window.
        """
        async with self._offense_lock:
            # Initialize if first offense
            if user_id not in self._offense_history:
                self._offense_history[user_id] = []

            # Add new offense
            self._offense_history[user_id].append(timestamp)

            # Clean up old offenses (outside the window)
            cutoff = timestamp - timedelta(seconds=RELIGION_OFFENSE_WINDOW)
            self._offense_history[user_id] = [
                ts for ts in self._offense_history[user_id] if ts > cutoff
            ]

            count = len(self._offense_history[user_id])
            logger.debug(f"Offense recorded for user {user_id}: {count}/{RELIGION_OFFENSE_THRESHOLD} in window")
            return count

    async def _auto_mute_user(self, message: discord.Message, offense_count: int) -> None:
        """
        Auto-mute a user for repeated religion talk violations.

        Args:
            message: The violating message.
            offense_count: Number of offenses in the window.
        """
        user_str = f"{message.author} ({message.author.id})"
        channel_str = f"#{message.channel.name}" if hasattr(message.channel, "name") else str(message.channel.id)
        duration_mins = RELIGION_AUTO_MUTE_MINUTES
        window_mins = RELIGION_OFFENSE_WINDOW // 60

        try:
            # Timeout the user
            await message.author.timeout(
                timedelta(minutes=RELIGION_AUTO_MUTE_MINUTES),
                reason=f"Auto-mute: {offense_count} religion talk violations in {window_mins} minutes"
            )

            logger.tree("AUTO-MUTE APPLIED", [
                ("User", user_str),
                ("Channel", channel_str),
                ("Offenses", f"{offense_count} in last {window_mins}m"),
                ("Duration", f"{duration_mins} minutes"),
            ], emoji="🔇")

            # Send mute notification to channel
            try:
                mute_msg = (
                    f"🔇 {message.author.mention} has been muted for {duration_mins} minutes.\n"
                    f"-# {offense_count} religion talk violations in the last hour"
                )
                await message.channel.send(mute_msg, delete_after=RELIGION_MUTE_MSG_DELETE_AFTER)
            except discord.HTTPException as e:
                logger.warning("Failed to Send Mute Notification", [
                    ("Channel", channel_str),
                    ("Error", str(e)[:50]),
                ])

            # Send mod alert for the auto-mute
            await self._send_auto_mute_alert(message, offense_count)

            # Clear their offense history after mute
            async with self._offense_lock:
                self._offense_history[message.author.id] = []

        except discord.Forbidden:
            logger.warning("Cannot Mute User", [
                ("User", user_str),
                ("Channel", channel_str),
                ("Reason", "Missing permissions or user has higher role"),
            ])
        except discord.HTTPException as e:
            logger.error("Auto-Mute Failed", [
                ("User", user_str),
                ("Channel", channel_str),
                ("Error", str(e)[:50]),
            ])

    async def _send_auto_mute_alert(self, message: discord.Message, offense_count: int) -> None:
        """
        Send alert to automod log thread for an auto-mute action.

        Args:
            message: The violating message.
            offense_count: Number of offenses that triggered the mute.
        """
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            logger.debug("Logging service not available for auto-mute alert")
            return

        duration_mins = RELIGION_AUTO_MUTE_MINUTES
        window_mins = RELIGION_OFFENSE_WINDOW // 60

        embed = discord.Embed(
            title="🔇 Auto-Mute: Repeated Religion Talk",
            color=EmbedColors.LOG_NEGATIVE,
            timestamp=datetime.now(NY_TZ),
        )
        embed.add_field(name="User", value=f"{message.author.mention}\n{message.author.id}", inline=True)
        embed.add_field(name="Channel", value=f"<#{message.channel.id}>", inline=True)
        embed.add_field(name="Duration", value=f"{duration_mins} minutes", inline=True)
        embed.add_field(
            name="Reason",
            value=f"{offense_count} religion talk violations in {window_mins} minutes",
            inline=False,
        )
        embed.add_field(
            name="Last Message",
            value=f"```{message.content[:500]}```" if message.content else "(no text)",
            inline=False,
        )
        set_footer(embed)

        try:
            from src.services.server_logs.categories import LogCategory
            await self.bot.logging_service._send_log(
                LogCategory.AUTOMOD,
                embed,
                user_id=message.author.id,
            )
            logger.debug(f"Auto-mute alert sent for user {message.author.id}")
        except discord.HTTPException as e:
            logger.warning("Failed to Send Auto-Mute Alert", [
                ("User", f"{message.author.id}"),
                ("Error", str(e)[:50]),
            ])
        except Exception as e:
            logger.error("Auto-Mute Alert Failed", [
                ("User", f"{message.author.id}"),
                ("Error", str(e)[:50]),
                ("Type", type(e).__name__),
            ])

    async def _send_violation_dm(
        self,
        message: discord.Message,
        result: ClassificationResult,
    ) -> None:
        """
        Send DM to user about their violation.

        Args:
            message: The violating message.
            result: The classification result.
        """
        try:
            dm_embed = discord.Embed(
                title=f"{VIOLATION_EMOJI} Message Removed",
                description=f"Your message in **{message.guild.name}** was removed for discussing religion.",
                color=EmbedColors.WARNING,
            )
            dm_embed.add_field(name="Server Rule", value="No religion discussions allowed", inline=False)
            dm_embed.add_field(
                name="Your Message",
                value=f"```{message.content[:500]}```" if message.content else "(no text)",
                inline=False,
            )
            dm_embed.set_footer(text="Please keep discussions secular. Repeated violations may result in mute.")
            await message.author.send(embed=dm_embed)
            logger.debug(f"Violation DM sent to user {message.author.id}")
        except discord.Forbidden:
            logger.debug(f"Cannot DM user {message.author.id}: DMs disabled")
        except discord.HTTPException as e:
            logger.debug(f"DM failed for user {message.author.id}: {e}")

    async def _send_mod_alert(
        self,
        message: discord.Message,
        result: ClassificationResult,
        deleted: bool,
    ) -> None:
        """
        Send alert to automod log thread.

        Args:
            message: The violating/flagged message.
            result: The classification result.
            deleted: Whether the message was deleted.
        """
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            logger.debug("Logging service not available for mod alert")
            return

        if deleted:
            title = f"{VIOLATION_EMOJI} Auto-Delete: Religion Talk Detected"
            color = EmbedColors.LOG_NEGATIVE
        else:
            title = f"{VIOLATION_EMOJI} Flagged for Review: Possible Religion Talk"
            color = EmbedColors.WARNING

        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=datetime.now(NY_TZ),
        )
        embed.add_field(name="User", value=f"{message.author.mention}\n{message.author.id}", inline=True)
        embed.add_field(name="Channel", value=f"<#{message.channel.id}>", inline=True)
        embed.add_field(name="Confidence", value=f"{result.confidence:.0%}", inline=True)
        embed.add_field(name="AI Reason", value=result.reason[:200], inline=False)
        embed.add_field(
            name="Message Content",
            value=f"```{message.content[:800]}```" if message.content else "(no text)",
            inline=False,
        )

        if not deleted:
            embed.add_field(
                name="Action Required",
                value=f"[Jump to Message]({message.jump_url})\nPlease review and take action if needed.",
                inline=False,
            )

        set_footer(embed)

        try:
            from src.services.server_logs.categories import LogCategory
            await self.bot.logging_service._send_log(
                LogCategory.AUTOMOD,
                embed,
                user_id=message.author.id,
            )
            logger.debug(f"Mod alert sent for user {message.author.id}")
        except discord.HTTPException as e:
            logger.warning("Failed to Send Mod Alert", [
                ("Error", str(e)[:50]),
            ])
        except Exception as e:
            logger.error("Mod Alert Failed", [
                ("Error", str(e)[:50]),
                ("Type", type(e).__name__),
            ])

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Clean up resources."""
        await self.classifier.close()
        logger.debug("Content Moderation Service closed")
