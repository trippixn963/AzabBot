"""
AzabBot - Anti-Spam Service
===========================

Main service class that combines all spam detection and handling.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.constants import DELETE_AFTER_EXTENDED
from src.core.database import get_db
from src.core.logger import logger
from src.utils.async_utils import create_safe_task
from src.utils.discord_rate_limit import log_http_error
from src.utils.footer import set_footer

from .constants import (
    ATTACHMENT_LIMIT,
    ATTACHMENT_TIME_WINDOW,
    CHANNEL_TYPE_MULTIPLIERS,
    DUPLICATE_LIMIT,
    DUPLICATE_MIN_LENGTH,
    DUPLICATE_TIME_WINDOW,
    EMOJI_LIMIT,
    FLOOD_MESSAGE_LIMIT,
    FLOOD_TIME_WINDOW,
    IMAGE_DUPLICATE_LIMIT,
    IMAGE_DUPLICATE_TIME_WINDOW,
    INVITE_LIMIT,
    INVITE_TIME_WINDOW,
    LINK_LIMIT,
    LINK_TIME_WINDOW,
    MAX_IMAGE_HASHES_PER_USER,
    MAX_TRACKED_USERS_PER_GUILD,
    MENTION_LIMIT,
    MESSAGE_HISTORY_CLEANUP,
    NEW_MEMBER_ACCOUNT_AGE,
    NEW_MEMBER_DUPLICATE_LIMIT,
    NEW_MEMBER_FLOOD_LIMIT,
    NEW_MEMBER_MENTION_LIMIT,
    NEW_MEMBER_SERVER_AGE,
    NEWLINE_LIMIT,
    REP_GAIN_MESSAGE,
    REPUTATION_UPDATE_INTERVAL,
    SLOWMODE_COOLDOWN,
    SLOWMODE_DURATION,
    SLOWMODE_TIME_WINDOW,
    SLOWMODE_TRIGGER_MESSAGES,
    STICKER_SPAM_LIMIT,
    STICKER_SPAM_TIME_WINDOW,
    VIOLATION_DECAY_TIME,
    WEBHOOK_TIME_WINDOW,
)
from .detectors import (
    count_emojis,
    count_newlines,
    extract_invites,
    hash_attachment,
    has_links,
    has_unsafe_links,
    is_emoji_only,
    is_exempt_greeting,
    is_mostly_arabic,
    is_scam,
    is_similar,
    is_whitelisted_invite,
    is_zalgo,
    LINK_PATTERN,
)
from .handlers import SpamHandlerMixin
from .models import MessageRecord, UserSpamState, WebhookState
from .raid import RaidDetectionMixin
from .reputation import ReputationMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class AntiSpamService(ReputationMixin, RaidDetectionMixin, SpamHandlerMixin):
    """
    Advanced spam detection and prevention.

    Features:
    - Progressive punishment system
    - User reputation tracking
    - Per-channel thresholds
    - Invite link detection with whitelist
    - Image hash matching
    - Enhanced raid detection
    - Webhook spam protection
    """

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the anti-spam service.

        Sets up all spam detection systems including:
        - User state tracking per guild
        - Channel message tracking for auto-slowmode
        - Webhook spam detection
        - Image hash duplicate detection
        - Reputation system
        - Raid detection
        - Background cleanup and reputation update tasks

        Args:
            bot: Main bot instance for Discord API access.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # Initialize mixins
        self._init_reputation()
        self._init_raid_detection()

        # User state tracking (guild_id -> user_id -> state)
        self._user_states: Dict[int, Dict[int, UserSpamState]] = defaultdict(
            lambda: defaultdict(UserSpamState)
        )

        # Channel message tracking for auto-slowmode (channel_id -> list of timestamps)
        self._channel_messages: Dict[int, List[datetime]] = defaultdict(list)
        self._slowmode_lock = asyncio.Lock()

        # Slowmode cooldowns (channel_id -> last slowmode time)
        self._slowmode_cooldowns: Dict[int, datetime] = {}

        # Webhook tracking (webhook_id -> WebhookState)
        self._webhook_states: Dict[int, WebhookState] = defaultdict(WebhookState)

        # Image hash cache (guild_id -> user_id -> list of (hash, timestamp))
        self._image_hashes: Dict[int, Dict[int, List[Tuple[str, datetime]]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Per-channel threshold overrides (channel_id -> multiplier)
        self._channel_multipliers: Dict[int, float] = {}

        # Exempt channels and roles
        self._exempt_channels: Set[int] = set()
        self._exempt_roles: Set[int] = set()

        self._load_exemptions()
        self._load_channel_multipliers()
        self._start_cleanup_task()
        self._start_reputation_task()

        logger.tree("Anti-Spam Service Loaded (Modular)", [
            ("Flood Limit", f"{FLOOD_MESSAGE_LIMIT} msgs / {FLOOD_TIME_WINDOW}s"),
            ("Duplicate Limit", f"{DUPLICATE_LIMIT}x"),
            ("Invite Detection", "Enabled with whitelist"),
            ("Reputation System", "Enabled"),
            ("Image Hashing", "Enabled"),
            ("Raid Detection", "Enhanced"),
            ("Webhook Protection", "Enabled"),
        ], emoji="🛡️")

    # =========================================================================
    # Initialization Helpers
    # =========================================================================

    def _load_exemptions(self) -> None:
        """
        Load exempt channels and roles from config.

        Exempts:
        - Prison channels (prisoners can't spam)
        - Mod/server log forums (bot-only)
        - Moderation role members
        - Server administrators
        """
        if self.config.prison_channel_ids:
            self._exempt_channels.update(self.config.prison_channel_ids)

        if self.config.mod_logs_forum_id:
            self._exempt_channels.add(self.config.mod_logs_forum_id)
        if self.config.server_logs_forum_id:
            self._exempt_channels.add(self.config.server_logs_forum_id)

        if self.config.moderation_role_id:
            self._exempt_roles.add(self.config.moderation_role_id)

    def _load_channel_multipliers(self) -> None:
        """
        Load per-channel threshold multipliers.

        Currently a placeholder for future configuration.
        Multipliers are calculated dynamically in _get_channel_multiplier.
        """
        pass

    def _get_channel_multiplier(self, channel: discord.abc.GuildChannel) -> float:
        """
        Get threshold multiplier for a channel based on its type/name.

        Different channel types have different spam tolerance:
        - Media channels: Higher tolerance (more images expected)
        - Bot command channels: Higher tolerance (rapid commands normal)
        - Vent/serious channels: Lower tolerance (quality over quantity)
        - Meme channels: Higher tolerance (rapid posting expected)
        - Counting channels: Much higher tolerance (one message per user)

        Args:
            channel: The channel to get multiplier for.

        Returns:
            Float multiplier (>1.0 = more lenient, <1.0 = stricter).
        """
        if channel.id in self._channel_multipliers:
            return self._channel_multipliers[channel.id]

        name = channel.name.lower() if hasattr(channel, 'name') else ""

        if any(x in name for x in ["media", "image", "photo", "art", "gallery"]):
            return CHANNEL_TYPE_MULTIPLIERS.get("media", 1.0)
        elif any(x in name for x in ["bot", "command", "cmd"]):
            return CHANNEL_TYPE_MULTIPLIERS.get("bot", 1.0)
        elif any(x in name for x in ["vent", "serious", "support"]):
            return CHANNEL_TYPE_MULTIPLIERS.get("vent", 1.0)
        elif any(x in name for x in ["meme", "shitpost", "funny"]):
            return CHANNEL_TYPE_MULTIPLIERS.get("meme", 1.0)
        elif any(x in name for x in ["counting", "count"]):
            return CHANNEL_TYPE_MULTIPLIERS.get("counting", 1.0)

        return 1.0

    # =========================================================================
    # Background Tasks
    # =========================================================================

    def _start_cleanup_task(self) -> None:
        """
        Start background task to clean old message records.

        Runs every MESSAGE_HISTORY_CLEANUP seconds to:
        - Remove expired message records from memory
        - Decay spam violations in database
        - Evict excess users from cache (LRU)
        - Clean image hash cache
        - Clean webhook state cache
        """
        create_safe_task(self._cleanup_loop(), "AntiSpam Cleanup Loop")

    def _start_reputation_task(self) -> None:
        """
        Start background task to update reputation scores.

        Runs every REPUTATION_UPDATE_INTERVAL seconds to clear
        reputation cache, forcing recalculation from database.
        """
        create_safe_task(self._reputation_loop(), "AntiSpam Reputation Loop")

    async def _cleanup_loop(self) -> None:
        """
        Periodically clean up old message records and decay DB violations.

        CLEANUP TASKS:
        1. Remove message records older than detection windows
        2. Decay spam violations in database (reduces punishment over time)
        3. Evict excess users from cache (LRU eviction)
        4. Clean image hash cache
        5. Clean webhook state cache
        6. Clean raid detection records

        Runs every MESSAGE_HISTORY_CLEANUP seconds.
        """
        while True:
            await asyncio.sleep(MESSAGE_HISTORY_CLEANUP)
            try:
                await self._cleanup_old_records()
                decayed = self.db.decay_spam_violations(VIOLATION_DECAY_TIME)
                if decayed > 0:
                    logger.debug("Spam Violations Decayed", [("Count", str(decayed))])
            except Exception as e:
                logger.warning("Anti-Spam Cleanup Error", [
                    ("Error", str(e)[:50]),
                ])

    async def _reputation_loop(self) -> None:
        """
        Periodically update reputation scores.

        Clears reputation cache to force recalculation from database.
        This ensures reputation changes (from good behavior or violations)
        are reflected in spam detection thresholds.

        Runs every REPUTATION_UPDATE_INTERVAL seconds.
        """
        while True:
            await asyncio.sleep(REPUTATION_UPDATE_INTERVAL)
            try:
                self.clear_reputation_cache()
            except Exception as e:
                logger.warning("Reputation Update Error", [
                    ("Error", str(e)[:50]),
                ])

    async def _cleanup_old_records(self) -> None:
        """
        Remove old message records from memory.

        MEMORY MANAGEMENT:
        - Removes message records older than 2x the longest detection window
        - Enforces MAX_TRACKED_USERS_PER_GUILD limit with LRU eviction
        - Limits image hashes per user to MAX_IMAGE_HASHES_PER_USER
        - Enforces max webhook states to prevent unbounded growth
        - Cleans raid detection records

        This prevents memory leaks in high-traffic servers.
        """
        now = datetime.now(NY_TZ)
        cutoff = now - timedelta(seconds=max(
            FLOOD_TIME_WINDOW,
            DUPLICATE_TIME_WINDOW,
            LINK_TIME_WINDOW,
            ATTACHMENT_TIME_WINDOW,
            INVITE_TIME_WINDOW,
            IMAGE_DUPLICATE_TIME_WINDOW,
        ) * 2)

        # Clean user message states
        for guild_id, guild_states in list(self._user_states.items()):
            for user_id, state in list(guild_states.items()):
                state.messages = [
                    m for m in state.messages
                    if m.timestamp > cutoff
                ]
                if not state.messages:
                    try:
                        del guild_states[user_id]
                    except KeyError:
                        pass  # Already removed by another coroutine

            if len(guild_states) > MAX_TRACKED_USERS_PER_GUILD:
                sorted_users = sorted(
                    guild_states.items(),
                    key=lambda x: x[1].messages[-1].timestamp if x[1].messages else cutoff
                )
                excess = len(guild_states) - MAX_TRACKED_USERS_PER_GUILD
                for user_id, _ in sorted_users[:excess]:
                    try:
                        del guild_states[user_id]
                    except KeyError:
                        pass  # Already removed
                logger.debug("Anti-Spam Cache Eviction", [("Guild", str(guild_id)), ("Evicted", str(excess))])

        # Clean image hashes
        image_cutoff = now - timedelta(seconds=IMAGE_DUPLICATE_TIME_WINDOW * 2)
        for guild_hashes in list(self._image_hashes.values()):
            for user_id, hashes in list(guild_hashes.items()):
                valid_hashes = [
                    (h, t) for h, t in hashes if t > image_cutoff
                ]
                if len(valid_hashes) > MAX_IMAGE_HASHES_PER_USER:
                    valid_hashes.sort(key=lambda x: x[1], reverse=True)
                    valid_hashes = valid_hashes[:MAX_IMAGE_HASHES_PER_USER]
                guild_hashes[user_id] = valid_hashes
                if not guild_hashes[user_id]:
                    try:
                        del guild_hashes[user_id]
                    except KeyError:
                        pass  # Already removed

        # Clean webhook states with size limit
        webhook_cutoff = now - timedelta(seconds=WEBHOOK_TIME_WINDOW * 2)
        for webhook_id, state in list(self._webhook_states.items()):
            state.messages = [t for t in state.messages if t > webhook_cutoff]
            if not state.messages:
                try:
                    del self._webhook_states[webhook_id]
                except KeyError:
                    pass

        # Enforce max webhook states to prevent unbounded growth
        MAX_WEBHOOK_STATES = 1000
        if len(self._webhook_states) > MAX_WEBHOOK_STATES:
            # Remove oldest webhook states
            sorted_webhooks = sorted(
                self._webhook_states.items(),
                key=lambda x: x[1].messages[-1] if x[1].messages else datetime.min.replace(tzinfo=NY_TZ)
            )
            excess = len(self._webhook_states) - MAX_WEBHOOK_STATES
            for webhook_id, _ in sorted_webhooks[:excess]:
                try:
                    del self._webhook_states[webhook_id]
                except KeyError:
                    pass

        # Clean raid records
        await self.cleanup_raid_records(now)

    # =========================================================================
    # Exemption Checks
    # =========================================================================

    def _is_exempt(self, message: discord.Message) -> bool:
        """
        Check if message/user is exempt from spam detection.

        EXEMPTIONS:
        - Bots (except webhooks, which are checked separately)
        - Messages in exempt channels (prison, logs, tickets)
        - Users with exempt roles (moderators)
        - Server administrators

        Args:
            message: Message to check for exemption.

        Returns:
            True if message should skip spam detection, False otherwise.
        """
        if message.author.bot and not message.webhook_id:
            return True

        if message.channel.id in self._exempt_channels:
            return True

        # Exempt ticket category channels
        if hasattr(message.channel, "category_id") and message.channel.category_id:
            if self.config.ticket_category_id and message.channel.category_id == self.config.ticket_category_id:
                return True

        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.id in self._exempt_roles:
                    return True

            if message.author.guild_permissions.administrator:
                return True

        return False

    def _is_new_member(self, member: discord.Member) -> bool:
        """
        Check if member is new (stricter spam rules apply).

        New members have:
        - Lower flood limits
        - Lower duplicate limits
        - Lower mention limits

        CRITERIA:
        - Account age < NEW_MEMBER_ACCOUNT_AGE days, OR
        - Server join age < NEW_MEMBER_SERVER_AGE days

        Args:
            member: Member to check.

        Returns:
            True if member is considered new, False otherwise.
        """
        now = datetime.now(NY_TZ)

        if member.created_at:
            account_age = (now - member.created_at.replace(tzinfo=NY_TZ)).days
            if account_age < NEW_MEMBER_ACCOUNT_AGE:
                return True

        if member.joined_at:
            server_age = (now - member.joined_at.replace(tzinfo=NY_TZ)).days
            if server_age < NEW_MEMBER_SERVER_AGE:
                return True

        return False

    # =========================================================================
    # Invite Spam Detection
    # =========================================================================

    async def _check_invite_spam(
        self, content: str, state: UserSpamState, now: datetime, guild_id: int
    ) -> bool:
        """
        Check if message contains non-whitelisted invite spam.

        LOGIC:
        1. Extract all Discord invite codes from message
        2. Filter out whitelisted invites (configured safe servers)
        3. Fetch each invite to check if it's for the same server
        4. Same-server invites are allowed (e.g., voice channel invites)
        5. Count external/invalid invites against limit

        Args:
            content: Message content to check.
            state: User's spam state for tracking invite count.
            now: Current timestamp.
            guild_id: Guild ID to check for same-server invites.

        Returns:
            True if invite spam detected (exceeded INVITE_LIMIT), False otherwise.
        """
        invites = extract_invites(content)
        if not invites:
            return False

        non_whitelisted = [i for i in invites if not is_whitelisted_invite(i)]
        if not non_whitelisted:
            return False

        logger.debug("Invite Check Started", [
            ("Total Invites", str(len(invites))),
            ("Non-Whitelisted", str(len(non_whitelisted))),
            ("Guild ID", str(guild_id)),
        ])

        # Filter out invites that are for the same server
        external_invites = []
        same_server_count = 0
        invalid_count = 0

        for invite_code in non_whitelisted:
            try:
                invite = await self.bot.fetch_invite(invite_code)
                if invite.guild and invite.guild.id == guild_id:
                    # Same server invite (e.g., voice channel invite) - allow it
                    same_server_count += 1
                    logger.tree("Same-Server Invite Allowed", [
                        ("Code", invite_code),
                        ("Guild", invite.guild.name if invite.guild else "Unknown"),
                        ("Channel", getattr(invite.channel, 'name', 'Unknown')),
                    ], emoji="✅")
                    continue
                # External server invite
                external_invites.append(invite_code)
                logger.tree("External Invite Detected", [
                    ("Code", invite_code),
                    ("Target Guild", invite.guild.name if invite.guild else "Unknown"),
                ], emoji="🔗")
            except discord.NotFound:
                # Invalid/expired invite - still count as external
                invalid_count += 1
                external_invites.append(invite_code)
                logger.debug("Invalid/Expired Invite", [
                    ("Code", invite_code),
                ])
            except discord.HTTPException as e:
                # API error - be lenient, don't count it
                logger.warning("Invite Fetch Failed", [
                    ("Code", invite_code),
                    ("Error", str(e)[:50]),
                ])

        if not external_invites:
            logger.debug("Invite Check Passed", [
                ("Same-Server", str(same_server_count)),
                ("Result", "All invites allowed"),
            ])
            return False

        if state.last_invite_time and (now - state.last_invite_time).total_seconds() < INVITE_TIME_WINDOW:
            state.invite_count += len(external_invites)
        else:
            state.invite_count = len(external_invites)
        state.last_invite_time = now

        is_spam = state.invite_count >= INVITE_LIMIT

        logger.tree("Invite Spam Check", [
            ("External Invites", str(len(external_invites))),
            ("Same-Server", str(same_server_count)),
            ("Invalid", str(invalid_count)),
            ("Total Count", str(state.invite_count)),
            ("Limit", str(INVITE_LIMIT)),
            ("Is Spam", str(is_spam)),
        ], emoji="🚨" if is_spam else "📊")

        return is_spam

    # =========================================================================
    # Image Duplicate Detection
    # =========================================================================

    def _check_image_duplicate(self, message: discord.Message, now: datetime) -> bool:
        """
        Check if user is posting duplicate images.

        Uses perceptual hashing to detect identical or near-identical images.
        Tracks hashes per user per guild with time window.

        ALGORITHM:
        1. Hash all image attachments in message
        2. Compare against user's recent image hashes
        3. Count matches within IMAGE_DUPLICATE_TIME_WINDOW
        4. Trigger if matches >= IMAGE_DUPLICATE_LIMIT

        Args:
            message: Message with potential image attachments.
            now: Current timestamp.

        Returns:
            True if duplicate image spam detected, False otherwise.
        """
        if not message.attachments:
            return False

        guild_id = message.guild.id
        user_id = message.author.id

        current_hashes = [
            hash_attachment(a) for a in message.attachments
            if a.content_type and a.content_type.startswith("image/")
        ]

        if not current_hashes:
            return False

        user_hashes = self._image_hashes[guild_id][user_id]
        cutoff = now - timedelta(seconds=IMAGE_DUPLICATE_TIME_WINDOW)

        for current_hash in current_hashes:
            match_count = sum(
                1 for h, t in user_hashes
                if h == current_hash and t > cutoff
            )
            if match_count >= IMAGE_DUPLICATE_LIMIT - 1:
                return True

        for h in current_hashes:
            user_hashes.append((h, now))

        return False

    # =========================================================================
    # Webhook Spam Detection
    # =========================================================================

    def _check_webhook_spam(self, message: discord.Message, now: datetime) -> bool:
        """
        Check if webhook is spamming.

        Webhooks can be abused for spam since they bypass user rate limits.
        Tracks message timestamps per webhook ID.

        EXEMPTIONS:
        - Whitelisted webhook IDs (configured trusted webhooks)

        Args:
            message: Message from webhook.
            now: Current timestamp.

        Returns:
            True if webhook spam detected (exceeded WEBHOOK_MESSAGE_LIMIT), False otherwise.
        """
        if not message.webhook_id:
            return False

        if self.config.whitelisted_webhook_ids and message.webhook_id in self.config.whitelisted_webhook_ids:
            return False

        state = self._webhook_states[message.webhook_id]
        cutoff = now - timedelta(seconds=WEBHOOK_TIME_WINDOW)

        state.messages = [t for t in state.messages if t > cutoff]
        state.messages.append(now)

        from .constants import WEBHOOK_MESSAGE_LIMIT
        return len(state.messages) > WEBHOOK_MESSAGE_LIMIT

    # =========================================================================
    # Auto-Slowmode
    # =========================================================================

    async def _check_auto_slowmode(self, message: discord.Message) -> None:
        """
        Check if channel needs auto-slowmode due to message flood.

        AUTO-SLOWMODE LOGIC:
        1. Track message timestamps per channel
        2. If SLOWMODE_TRIGGER_MESSAGES messages in SLOWMODE_TIME_WINDOW seconds
        3. Apply SLOWMODE_DURATION second slowmode
        4. Cooldown prevents repeated slowmode triggers

        This helps prevent spam waves without manual intervention.

        Args:
            message: Message that might trigger auto-slowmode.
        """
        if not message.guild or not isinstance(message.channel, discord.TextChannel):
            return

        channel_id = message.channel.id
        now = datetime.now(NY_TZ)

        if channel_id in self._slowmode_cooldowns:
            cooldown_end = self._slowmode_cooldowns[channel_id] + timedelta(seconds=SLOWMODE_COOLDOWN)
            if now < cooldown_end:
                return

        # Use lock to prevent race conditions when modifying _channel_messages
        async with self._slowmode_lock:
            self._channel_messages[channel_id].append(now)

            cutoff = now - timedelta(seconds=SLOWMODE_TIME_WINDOW)
            self._channel_messages[channel_id] = [
                t for t in self._channel_messages[channel_id] if t > cutoff
            ]

            should_slowmode = len(self._channel_messages[channel_id]) >= SLOWMODE_TRIGGER_MESSAGES
            if should_slowmode:
                self._slowmode_cooldowns[channel_id] = now
                self._channel_messages[channel_id] = []

        if should_slowmode:
            await self._apply_slowmode(message.channel)

    async def _apply_slowmode(self, channel: discord.TextChannel) -> None:
        """
        Apply temporary slowmode to a channel.

        WORKFLOW:
        1. Save original slowmode delay
        2. Apply SLOWMODE_DURATION second slowmode
        3. Send notification embed
        4. Wait for duration
        5. Restore original slowmode

        Args:
            channel: Channel to apply slowmode to.
        """
        try:
            original_slowmode = channel.slowmode_delay
            await channel.edit(slowmode_delay=SLOWMODE_DURATION)

            embed = discord.Embed(
                title="🐌 Slowmode Enabled",
                description="Auto-slowmode activated due to high message volume.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Duration", value=f"{SLOWMODE_DURATION}s", inline=True)
            embed.add_field(name="Reason", value="Spam wave detected", inline=True)
            set_footer(embed)

            await channel.send(embed=embed, delete_after=DELETE_AFTER_EXTENDED)

            logger.tree("AUTO-SLOWMODE ENABLED", [
                ("Channel", f"#{channel.name}"),
                ("Channel ID", str(channel.id)),
                ("Duration", f"{SLOWMODE_DURATION}s"),
                ("Trigger", f"{SLOWMODE_TRIGGER_MESSAGES} msgs in {SLOWMODE_TIME_WINDOW}s"),
            ], emoji="🐌")

            await asyncio.sleep(SLOWMODE_DURATION)

            try:
                await channel.edit(slowmode_delay=original_slowmode)
                logger.tree("AUTO-SLOWMODE DISABLED", [
                    ("Channel", f"#{channel.name}"),
                    ("Channel ID", str(channel.id)),
                ], emoji="🐌")
            except discord.HTTPException:
                logger.tree("Auto-Slowmode Disable Failed", [
                    ("Channel", f"#{channel.name}"),
                    ("Channel ID", str(channel.id)),
                    ("Reason", "Channel deleted or no permission"),
                ], emoji="⚠️")

        except discord.Forbidden:
            logger.warning("Slowmode Permission Denied", [
                ("Channel", f"#{channel.name}"),
                ("Channel ID", str(channel.id)),
            ])
        except discord.HTTPException as e:
            logger.warning("Slowmode Failed", [
                ("Channel", f"#{channel.name}"),
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Main Spam Detection
    # =========================================================================

    async def check_message(self, message: discord.Message) -> Optional[str]:
        """
        Check a message for spam using all detection methods.

        DETECTION PIPELINE (in order):
        1. Exemption check (bots, mods, admins)
        2. Webhook spam
        3. Scam/phishing detection
        4. Zalgo text detection
        5. Invite spam (with same-server filtering)
        6. Message flood
        7. Duplicate message spam
        8. Image duplicate spam
        9. Mention spam
        10. Emoji spam
        11. Newline spam
        12. Link flood
        13. Attachment flood
        14. Sticker spam

        ADAPTIVE THRESHOLDS:
        - New members have stricter limits
        - Reputation multiplier adjusts thresholds
        - Channel type multiplier adjusts thresholds
        - Combined multiplier = reputation × channel type

        REPUTATION SYSTEM:
        - Good behavior increases reputation (higher thresholds)
        - Spam violations decrease reputation (lower thresholds)
        - Reputation decays over time in database

        Args:
            message: Message to check for spam.

        Returns:
            Spam type string if spam detected (e.g., "message_flood", "scam"),
            None if message is clean.
        """
        if self._is_exempt(message):
            return None

        if not message.guild:
            return None

        if self.config.mod_server_id and message.guild.id == self.config.mod_server_id:
            return None

        guild_id = message.guild.id
        user_id = message.author.id
        now = datetime.now(NY_TZ)

        # Check webhook spam first
        if message.webhook_id:
            if self._check_webhook_spam(message, now):
                return "webhook_spam"
            return None

        state = self._user_states[guild_id][user_id]

        # Create message record
        content = message.content or ""
        invites = extract_invites(content)

        record = MessageRecord(
            content=content.lower().strip(),
            timestamp=now,
            has_links=has_unsafe_links(content),  # Only count non-whitelisted links
            has_attachments=len(message.attachments) > 0,
            has_invites=bool(invites),
            has_stickers=len(message.stickers) > 0,
            mention_count=len(message.mentions) + len(message.role_mentions),
            emoji_count=count_emojis(content),
            attachment_hashes=[hash_attachment(a) for a in message.attachments],
        )

        state.messages.append(record)

        # Get multipliers
        is_new = isinstance(message.author, discord.Member) and self._is_new_member(message.author)
        rep_multiplier = self.get_reputation_multiplier(user_id, guild_id)
        channel_multiplier = self._get_channel_multiplier(message.channel)
        total_multiplier = rep_multiplier * channel_multiplier

        # Set thresholds
        if is_new:
            flood_limit = int(NEW_MEMBER_FLOOD_LIMIT * total_multiplier)
            duplicate_limit = int(NEW_MEMBER_DUPLICATE_LIMIT * total_multiplier)
            mention_limit = int(NEW_MEMBER_MENTION_LIMIT * total_multiplier)
        else:
            flood_limit = int(FLOOD_MESSAGE_LIMIT * total_multiplier)
            duplicate_limit = int(DUPLICATE_LIMIT * total_multiplier)
            mention_limit = int(MENTION_LIMIT * total_multiplier)

        flood_limit = max(flood_limit, 3)
        duplicate_limit = max(duplicate_limit, 2)
        mention_limit = max(mention_limit, 2)

        await self._check_auto_slowmode(message)

        if is_exempt_greeting(content):
            self.update_reputation(user_id, guild_id, REP_GAIN_MESSAGE)
            return None

        spam_type = None

        # 1. Scam/Phishing
        if is_scam(content):
            spam_type = "scam"

        # 2. Zalgo
        if not spam_type and is_zalgo(content):
            spam_type = "zalgo"

        # 3. Invite spam
        if not spam_type and await self._check_invite_spam(content, state, now, guild_id):
            spam_type = "invite_spam"

        # 4. Message flood
        if not spam_type:
            recent_messages = [
                m for m in state.messages
                if (now - m.timestamp).total_seconds() < FLOOD_TIME_WINDOW
            ]
            if len(recent_messages) > flood_limit:
                spam_type = "message_flood"

        # 5. Duplicate spam
        is_arabic = is_mostly_arabic(content)
        is_emoji = is_emoji_only(content)
        if not spam_type and record.content and len(record.content) >= DUPLICATE_MIN_LENGTH and not is_arabic and not is_emoji:
            similar_count = 0
            for m in state.messages:
                if m is not record and (now - m.timestamp).total_seconds() < DUPLICATE_TIME_WINDOW:
                    if is_similar(m.content, record.content):
                        similar_count += 1
            if similar_count >= duplicate_limit - 1:
                spam_type = "duplicate"

        # 6. Image duplicate
        if not spam_type and self._check_image_duplicate(message, now):
            spam_type = "image_duplicate"

        # 7. Mention spam (skip if channel is whitelisted)
        is_mention_exempt = (
            self.config.mention_spam_exempt_channel_ids
            and message.channel.id in self.config.mention_spam_exempt_channel_ids
        )
        if not spam_type and not is_mention_exempt and record.mention_count >= mention_limit:
            spam_type = "mention_spam"

        # 8. Emoji spam
        emoji_limit = int(EMOJI_LIMIT * total_multiplier)
        if not spam_type and record.emoji_count >= emoji_limit:
            spam_type = "emoji_spam"

        # 9. Newline spam
        newline_limit = int(NEWLINE_LIMIT * total_multiplier)
        if not spam_type and not is_arabic and count_newlines(content) >= newline_limit:
            spam_type = "newline_spam"

        # 10. Link flood
        if not spam_type and record.has_links:
            link_limit = int(LINK_LIMIT * total_multiplier)
            recent_links = [
                m for m in state.messages
                if m.has_links
                and (now - m.timestamp).total_seconds() < LINK_TIME_WINDOW
            ]
            if len(recent_links) >= link_limit:
                spam_type = "link_flood"

        # 11. Attachment flood
        if not spam_type and record.has_attachments:
            attachment_limit = int(ATTACHMENT_LIMIT * total_multiplier)
            recent_attachments = [
                m for m in state.messages
                if m.has_attachments
                and (now - m.timestamp).total_seconds() < ATTACHMENT_TIME_WINDOW
            ]
            if len(recent_attachments) >= attachment_limit:
                spam_type = "attachment_flood"

        # 12. Sticker spam
        if not spam_type and record.has_stickers:
            recent_sticker_msgs = [
                m for m in state.messages
                if m.has_stickers
                and (now - m.timestamp).total_seconds() < STICKER_SPAM_TIME_WINDOW
            ]
            if len(recent_sticker_msgs) >= STICKER_SPAM_LIMIT:
                spam_type = "sticker_spam"

        if not spam_type:
            self.update_reputation(user_id, guild_id, REP_GAIN_MESSAGE)

        return spam_type


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AntiSpamService"]
