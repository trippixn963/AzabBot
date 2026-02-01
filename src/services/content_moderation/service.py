"""
AzabBot - Content Moderation Service
====================================

AI-powered content moderation for detecting religion discussions.
"""

import asyncio
import hashlib
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, TYPE_CHECKING

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.logger import logger
from src.utils.footer import set_footer

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
    """

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.classifier = ContentClassifier()

        # Rate limiting
        self._api_calls: list[datetime] = []
        self._api_lock = asyncio.Lock()

        # User cooldowns (user_id -> last check time)
        self._user_cooldowns: Dict[int, datetime] = {}

        # Classification cache (content_hash -> (result, timestamp))
        self._cache: OrderedDict[str, tuple[ClassificationResult, datetime]] = OrderedDict()

        # Exempt channels (mod channels, etc.)
        self._exempt_channels: Set[int] = set()
        self._exempt_roles: Set[int] = set()
        self._load_exemptions()

        if self.enabled:
            logger.tree("Content Moderation Service Loaded", [
                ("Classifier", "OpenAI GPT-4o-mini"),
                ("Delete Threshold", f"{CONFIDENCE_THRESHOLD_DELETE:.0%}"),
                ("Alert Threshold", f"{CONFIDENCE_THRESHOLD_ALERT:.0%}"),
                ("Rate Limit", f"{MAX_API_CALLS_PER_MINUTE}/min"),
            ], emoji=VIOLATION_EMOJI)
        else:
            logger.info("Content Moderation Service Disabled (no API key)")

    @property
    def enabled(self) -> bool:
        """Check if service is enabled."""
        return self.classifier.enabled

    def _load_exemptions(self) -> None:
        """Load exempt channels and roles."""
        # Exempt mod/log channels
        if self.config.mod_logs_forum_id:
            self._exempt_channels.add(self.config.mod_logs_forum_id)
        if self.config.server_logs_forum_id:
            self._exempt_channels.add(self.config.server_logs_forum_id)
        if self.config.case_log_forum_id:
            self._exempt_channels.add(self.config.case_log_forum_id)

        # Exempt mod role
        if self.config.moderation_role_id:
            self._exempt_roles.add(self.config.moderation_role_id)

    def _is_exempt(self, message: discord.Message) -> bool:
        """Check if message is exempt from moderation."""
        # Bots are exempt
        if message.author.bot:
            return True

        # Check channel exemptions
        channel_id = message.channel.id
        if channel_id in self._exempt_channels:
            return True

        # Check if in exempt forum thread
        if isinstance(message.channel, discord.Thread):
            if message.channel.parent_id in self._exempt_channels:
                return True

        # Check role exemptions
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.id in self._exempt_roles:
                    return True
            # Admins exempt
            if message.author.guild_permissions.administrator:
                return True

        return False

    def _hash_content(self, content: str) -> str:
        """Create hash of content for caching."""
        normalized = content.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    def _get_cached_result(self, content_hash: str) -> Optional[ClassificationResult]:
        """Get cached classification result if valid."""
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
        return result

    def _cache_result(self, content_hash: str, result: ClassificationResult) -> None:
        """Cache classification result."""
        # Evict oldest if at limit
        while len(self._cache) >= CLASSIFICATION_CACHE_SIZE:
            self._cache.popitem(last=False)

        self._cache[content_hash] = (result, datetime.now(NY_TZ))

    async def _check_rate_limit(self) -> bool:
        """Check if we can make an API call (returns True if allowed)."""
        async with self._api_lock:
            now = datetime.now(NY_TZ)
            cutoff = now - timedelta(minutes=1)

            # Remove old entries
            self._api_calls = [t for t in self._api_calls if t > cutoff]

            if len(self._api_calls) >= MAX_API_CALLS_PER_MINUTE:
                return False

            self._api_calls.append(now)
            return True

    def _check_user_cooldown(self, user_id: int) -> bool:
        """Check if user is on cooldown (returns True if NOT on cooldown)."""
        now = datetime.now(NY_TZ)
        last_check = self._user_cooldowns.get(user_id)

        if last_check and (now - last_check).total_seconds() < USER_CHECK_COOLDOWN:
            return False

        self._user_cooldowns[user_id] = now
        return True

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
        if self._is_exempt(message):
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
        if not self._check_user_cooldown(message.author.id):
            return None

        # Check cache
        content_hash = self._hash_content(content)
        cached = self._get_cached_result(content_hash)
        if cached is not None:
            return cached

        # Check rate limit
        if not await self._check_rate_limit():
            logger.debug("Content moderation rate limited")
            return None

        # Classify
        result = await self.classifier.classify(content)

        # Cache result
        self._cache_result(content_hash, result)

        return result

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
        """Handle high-confidence violation (auto-delete + warn)."""
        try:
            # Delete the message
            await message.delete()

            # Send warning embed to channel
            embed = discord.Embed(
                title=f"{VIOLATION_EMOJI} {VIOLATION_TYPE} Detected",
                description=f"{message.author.mention}, discussing religion is not allowed in this server.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Rule", value="No religion talk", inline=True)
            embed.add_field(name="Confidence", value=f"{result.confidence:.0%}", inline=True)
            set_footer(embed)

            warning_msg = await message.channel.send(embed=embed, delete_after=15)

            # Log the action
            logger.tree("RELIGION TALK DELETED", [
                ("User", f"{message.author} ({message.author.id})"),
                ("Channel", f"#{message.channel.name}"),
                ("Confidence", f"{result.confidence:.0%}"),
                ("Reason", result.reason[:50]),
                ("Content", message.content[:50] + "..." if len(message.content) > 50 else message.content),
            ], emoji=VIOLATION_EMOJI)

            # Try to DM the user
            try:
                dm_embed = discord.Embed(
                    title=f"{VIOLATION_EMOJI} Message Removed",
                    description=f"Your message in **{message.guild.name}** was removed for discussing religion.",
                    color=EmbedColors.WARNING,
                )
                dm_embed.add_field(name="Server Rule", value="No religion discussions allowed", inline=False)
                dm_embed.add_field(name="Your Message", value=f"```{message.content[:500]}```", inline=False)
                dm_embed.set_footer(text="Please keep discussions secular. Repeated violations may result in mute.")
                await message.author.send(embed=dm_embed)
            except discord.Forbidden:
                logger.debug(f"Could not DM user {message.author.id} about religion violation")

            # Alert mods (optional - send to alert channel if configured)
            await self._send_mod_alert(message, result, deleted=True)

        except discord.Forbidden:
            logger.warning("No permission to delete religion talk message", [
                ("Channel", f"#{message.channel.name}"),
                ("User", str(message.author)),
            ])
        except discord.HTTPException as e:
            logger.error("Failed to handle religion violation", [
                ("Error", str(e)[:50]),
            ])

    async def _handle_medium_confidence(
        self,
        message: discord.Message,
        result: ClassificationResult,
    ) -> None:
        """Handle medium-confidence violation (alert mods only)."""
        logger.tree("RELIGION TALK FLAGGED (Low Confidence)", [
            ("User", f"{message.author} ({message.author.id})"),
            ("Channel", f"#{message.channel.name}"),
            ("Confidence", f"{result.confidence:.0%}"),
            ("Reason", result.reason[:50]),
        ], emoji="🚩")

        # Alert mods for review
        await self._send_mod_alert(message, result, deleted=False)

    async def _send_mod_alert(
        self,
        message: discord.Message,
        result: ClassificationResult,
        deleted: bool,
    ) -> None:
        """Send alert to automod log thread."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        status = "Deleted" if deleted else "Flagged for Review"
        color = EmbedColors.LOG_NEGATIVE if deleted else EmbedColors.WARNING

        embed = discord.Embed(
            title=f"{VIOLATION_EMOJI} Religion Discussion {status}",
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
        except Exception as e:
            logger.warning("Failed to send religion alert", [
                ("Error", str(e)[:50]),
            ])

    async def close(self) -> None:
        """Clean up resources."""
        await self.classifier.close()
