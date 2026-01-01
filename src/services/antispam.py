"""
Azab Discord Bot - Anti-Spam Service (Enhanced)
================================================

Automatic spam detection and prevention system with advanced features.

DESIGN:
    Tracks message patterns per user and detects various spam types.
    Uses progressive punishment: warn → short mute → longer mute.
    Integrates with case logging and server logs.
    Persists violations to database (survives restarts).
    Includes reputation system for trusted members.

Spam Types Detected:
    - Message flood: Too many messages too fast
    - Duplicate spam: Similar messages repeated (fuzzy matching)
    - Mention spam: Too many mentions
    - Emoji spam: Excessive emojis
    - Link flood: Multiple links in short time
    - Invite spam: Discord invite links to other servers
    - Caps spam: Excessive capital letters
    - Newline spam: Excessive line breaks
    - Character spam: Repeated characters
    - Attachment flood: Too many attachments
    - Image duplicate: Same image posted repeatedly
    - Zalgo/Unicode abuse: Malicious unicode text
    - Webhook spam: Spam from webhooks

Advanced Features:
    - User reputation system (trusted members get leniency)
    - Per-channel thresholds
    - Enhanced raid detection (similar accounts/avatars/usernames)
    - Invite link detection with whitelist
    - Image hash matching

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import hashlib
import re
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.views import CASE_EMOJI
from src.utils.async_utils import create_safe_task

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants - Thresholds (Not Too Strict)
# =============================================================================

# Message flood: X messages in Y seconds
FLOOD_MESSAGE_LIMIT = 6  # 6 messages in 5 seconds = spam
FLOOD_TIME_WINDOW = 5  # seconds

# Duplicate spam: Similar messages X times in Y seconds
DUPLICATE_LIMIT = 3  # 3 similar messages = spam
DUPLICATE_TIME_WINDOW = 30  # seconds
DUPLICATE_SIMILARITY_THRESHOLD = 0.85  # 85% similar = duplicate

# Mention spam: X mentions in one message
MENTION_LIMIT = 5

# Emoji spam: X emojis in one message
EMOJI_LIMIT = 20  # reasonable for expressive chat

# Link flood: X links in Y seconds
LINK_LIMIT = 3
LINK_TIME_WINDOW = 30  # seconds

# Invite spam: X invites in Y seconds (strict)
INVITE_LIMIT = 1  # any invite is suspicious
INVITE_TIME_WINDOW = 60  # seconds

# Caps spam: X% caps in message with min length
CAPS_PERCENTAGE = 75
CAPS_MIN_LENGTH = 12

# Newline spam: X newlines in one message (still lenient for Quran verses)
NEWLINE_LIMIT = 20

# Character spam: Same char repeated X+ times
CHAR_REPEAT_LIMIT = 15

# Image duplicate: Same image X times in Y seconds
IMAGE_DUPLICATE_LIMIT = 3
IMAGE_DUPLICATE_TIME_WINDOW = 60  # seconds

# Webhook spam: X messages in Y seconds from webhooks
WEBHOOK_MESSAGE_LIMIT = 5
WEBHOOK_TIME_WINDOW = 10  # seconds

# Memory bounds: Maximum tracked users per guild to prevent unbounded growth
MAX_TRACKED_USERS_PER_GUILD = 5000

# Arabic characters range (exempt from char spam and lenient on duplicates)
# Arabic script: U+0600 to U+06FF
ARABIC_RANGE = range(0x0600, 0x06FF + 1)

# Arabic tashkeel (diacritical marks) to strip for normalization
# These are: fatha, kasra, damma, sukun, shadda, tanween, etc.
ARABIC_TASHKEEL = frozenset([
    '\u064B',  # tanween fatha
    '\u064C',  # tanween damma
    '\u064D',  # tanween kasra
    '\u064E',  # fatha
    '\u064F',  # damma
    '\u0650',  # kasra
    '\u0651',  # shadda
    '\u0652',  # sukun
    '\u0653',  # maddah
    '\u0654',  # hamza above
    '\u0655',  # hamza below
    '\u0656',  # subscript alef
    '\u0670',  # superscript alef
])

# Common Arabic/Islamic greetings (always exempt from spam detection)
# Stored WITHOUT tashkeel - input is normalized before comparison
EXEMPT_ARABIC_GREETINGS = {
    # Salam variations
    "السلام عليكم",
    "السلام عليكم ورحمة الله",
    "السلام عليكم ورحمة الله وبركاته",
    "سلام عليكم",
    "سلام",
    # Wa alaykum salam variations
    "وعليكم السلام",
    "وعليكم السلام ورحمة الله",
    "وعليكم السلام ورحمة الله وبركاته",
    "عليكم السلام",
    "عليكم السلام ورحمة الله وبركاته",
    # General greetings
    "صباح الخير",
    "صباح النور",
    "مساء الخير",
    "مساء النور",
    "مرحبا",
    "مرحبا بك",
    "مرحبا بكم",
    "اهلا",
    "اهلا بك",
    "اهلا بكم",
    "اهلا وسهلا",
    "اهلا وسهلا بك",
    "اهلا وسهلا بكم",
    "هلا",
    "هلا والله",
    "يا هلا",
    # Islamic phrases
    "الحمد لله",
    "الحمدلله",
    "سبحان الله",
    "سبحانه وتعالى",
    "الله اكبر",
    "لا اله الا الله",
    "ماشاء الله",
    "ما شاء الله",
    "تبارك الله",
    "استغفر الله",
    "استغفرالله",
    "بسم الله",
    "بسم الله الرحمن الرحيم",
    "ان شاء الله",
    "انشاء الله",
    "لا حول ولا قوة الا بالله",
    # Duas/blessings
    "جزاك الله خيرا",
    "جزاك الله خير",
    "جزاكم الله خيرا",
    "جزاكم الله خير",
    "بارك الله فيك",
    "بارك الله فيكم",
    "الله يبارك فيك",
    "الله يبارك فيكم",
    "الله يعطيك العافية",
    "الله يعافيك",
    "الله يحفظك",
    "الله يحفظكم",
    "الله يسلمك",
    "الله يسعدك",
    "الله يوفقك",
    "الله يرحمك",
    "رحمه الله",
    "رحمها الله",
    "يرحمك الله",
    "الله يهديك",
    "هداك الله",
    "الله يكرمك",
    "الله يعينك",
    "الله معك",
    "الله معاك",
    "توكلت على الله",
    "حسبي الله ونعم الوكيل",
    "صلى الله عليه وسلم",
    "عليه السلام",
    "رضي الله عنه",
    "رضي الله عنها",
}

# Minimum length for duplicate detection (short messages ignored)
DUPLICATE_MIN_LENGTH = 150  # ignore short/casual repeated messages (incl emoji spam)

# Attachment flood: X attachments in Y seconds
ATTACHMENT_LIMIT = 5
ATTACHMENT_TIME_WINDOW = 30  # seconds

# Zalgo detection: X+ combining characters
ZALGO_COMBINING_LIMIT = 10


# =============================================================================
# Invite Detection
# =============================================================================

# Discord invite patterns
DISCORD_INVITE_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?'
    r'(?:discord\.gg|discord\.com/invite|discordapp\.com/invite)/'
    r'([a-zA-Z0-9\-]+)',
    re.IGNORECASE
)

# Whitelisted invite codes (your server's invites)
# Add your server's permanent invite codes here
WHITELISTED_INVITE_CODES = {
    "syria",  # discord.gg/syria
}


# =============================================================================
# Reputation System
# =============================================================================

# Reputation thresholds
REPUTATION_NEW = 0        # New users
REPUTATION_REGULAR = 50   # Regular members
REPUTATION_TRUSTED = 100  # Trusted members
REPUTATION_VETERAN = 200  # Veterans

# Reputation gains
REP_GAIN_MESSAGE = 0.1          # Per non-spam message
REP_GAIN_DAY_ACTIVE = 1         # Per day active
REP_GAIN_WEEK_NO_VIOLATION = 5  # Bonus for clean week

# Reputation losses
REP_LOSS_WARNING = 10      # Per spam warning
REP_LOSS_MUTE = 25         # Per spam mute
REP_LOSS_KICK = 50         # If kicked
REP_LOSS_BAN = 100         # If banned (stored for if unbanned)

# Threshold multipliers based on reputation
# Higher reputation = more lenient thresholds
REPUTATION_MULTIPLIERS = {
    REPUTATION_NEW: 1.0,       # Default thresholds
    REPUTATION_REGULAR: 1.25,  # 25% more lenient
    REPUTATION_TRUSTED: 1.5,   # 50% more lenient
    REPUTATION_VETERAN: 2.0,   # 100% more lenient (double thresholds)
}


# =============================================================================
# Per-Channel Thresholds
# =============================================================================

# Channel type overrides (channel_id -> threshold multiplier)
# Multiplier > 1 = more lenient, < 1 = stricter
# Configure in config or set defaults based on channel type
CHANNEL_TYPE_MULTIPLIERS = {
    "media": 2.0,      # Media channels: allow more attachments
    "bot": 0.5,        # Bot channels: stricter (prevent abuse)
    "vent": 1.5,       # Vent channels: more lenient
    "meme": 1.5,       # Meme channels: more lenient
    "counting": 0.1,   # Counting channels: very strict (one message at a time)
}


# =============================================================================
# Enhanced Raid Detection
# =============================================================================

# Raid detection: X new accounts in Y seconds
RAID_JOIN_LIMIT = 5
RAID_TIME_WINDOW = 30  # seconds

# Enhanced raid detection thresholds
RAID_SIMILAR_NAME_THRESHOLD = 0.7     # 70% name similarity = suspicious
RAID_ACCOUNT_AGE_HOURS = 24           # Accounts less than 24h old
RAID_DEFAULT_AVATAR_WEIGHT = 2        # Default avatar counts as 2 suspicious joins
RAID_SIMILAR_CREATION_WINDOW = 3600   # Accounts created within 1 hour of each other

# New account threshold for raids
NEW_ACCOUNT_DAYS = 7

# New member thresholds (stricter for accounts < 30 days or joined < 7 days)
NEW_MEMBER_ACCOUNT_AGE = 30  # days
NEW_MEMBER_SERVER_AGE = 7   # days
NEW_MEMBER_FLOOD_LIMIT = 5  # stricter than regular 8
NEW_MEMBER_DUPLICATE_LIMIT = 2  # stricter than regular 4
NEW_MEMBER_MENTION_LIMIT = 3  # stricter than regular 6


# =============================================================================
# Scam Detection Patterns
# =============================================================================

# Common scam phrases (case insensitive)
SCAM_PHRASES = [
    # Nitro scams
    "free nitro",
    "discord nitro free",
    "nitro gift from",
    "claim your nitro",
    "get nitro free",
    "free discord nitro",
    "nitro giveaway http",
    # Crypto scams
    "free btc",
    "free eth",
    "free crypto",
    "send me eth",
    "send me btc",
    "double your crypto",
    "crypto giveaway",
    "airdrop claim",
    # Steam scams
    "free steam",
    "steam gift",
    "vote for my team",
    "vote for our team",
    # Generic scams
    "click this link to claim",
    "you have been selected",
    "you have won",
    "claim your prize",
    "congratulations you won",
]

# Phishing domain patterns (partial matches)
PHISHING_DOMAINS = [
    "discord.gift",  # Legit, but often used in scams with other text
    "discordgift.",
    "discrod.",
    "dlscord.",
    "disc0rd.",
    "discorcl.",
    "discard.",
    "steamcommunlty.",
    "steamncommnunity.",
    "steamcommunity.ru",
    "steamcommunity.co",
    "tradeoffer.",
    "csgo-trade.",
    "free-nitro.",
    "nitro-gift.",
    "discord-nitro.",
    "claim-nitro.",
]

# Crypto wallet patterns (Ethereum/Bitcoin addresses in scam context)
CRYPTO_WALLET_PATTERN = r'(?:0x[a-fA-F0-9]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})'


# =============================================================================
# Auto-Slowmode Settings
# =============================================================================

SLOWMODE_TRIGGER_MESSAGES = 25  # Messages in time window to trigger slowmode
SLOWMODE_TIME_WINDOW = 10  # seconds
SLOWMODE_DURATION = 5  # seconds of slowmode
SLOWMODE_COOLDOWN = 300  # 5 minutes before slowmode can trigger again


# =============================================================================
# Cleanup Intervals
# =============================================================================

MESSAGE_HISTORY_CLEANUP = 60  # seconds
VIOLATION_DECAY_TIME = 300  # 5 minutes - violations decay after this
REPUTATION_UPDATE_INTERVAL = 3600  # 1 hour - update reputation scores


# =============================================================================
# Punishment Durations (Progressive)
# =============================================================================

MUTE_DURATIONS = {
    1: 0,      # First offense: warning only
    2: 300,    # Second offense: 5 minutes
    3: 1800,   # Third offense: 30 minutes
    4: 3600,   # Fourth offense: 1 hour
    5: 86400,  # Fifth+ offense: 24 hours
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MessageRecord:
    """Record of a message for spam detection."""
    content: str
    timestamp: datetime
    has_links: bool = False
    has_attachments: bool = False
    has_invites: bool = False
    mention_count: int = 0
    emoji_count: int = 0
    attachment_hashes: List[str] = field(default_factory=list)


@dataclass
class UserSpamState:
    """Tracks spam state for a user (in-memory for recent messages)."""
    messages: List[MessageRecord] = field(default_factory=list)
    invite_count: int = 0
    last_invite_time: Optional[datetime] = None


@dataclass
class JoinRecord:
    """Record of a member join for raid detection."""
    user_id: int
    username: str
    display_name: str
    account_created: datetime
    has_default_avatar: bool
    avatar_hash: Optional[str]
    join_time: datetime


@dataclass
class WebhookState:
    """Tracks webhook message state."""
    messages: List[datetime] = field(default_factory=list)


# =============================================================================
# Anti-Spam Service
# =============================================================================

class AntiSpamService:
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
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # User state tracking for recent messages (guild_id -> user_id -> state)
        self._user_states: Dict[int, Dict[int, UserSpamState]] = defaultdict(
            lambda: defaultdict(UserSpamState)
        )

        # Recent joins for raid detection (guild_id -> list of JoinRecords)
        self._recent_joins: Dict[int, List[JoinRecord]] = defaultdict(list)

        # Channel message tracking for auto-slowmode (channel_id -> list of timestamps)
        self._channel_messages: Dict[int, List[datetime]] = defaultdict(list)

        # Slowmode cooldowns (channel_id -> last slowmode time)
        self._slowmode_cooldowns: Dict[int, datetime] = {}

        # Webhook tracking (webhook_id -> WebhookState)
        self._webhook_states: Dict[int, WebhookState] = defaultdict(WebhookState)

        # Image hash cache (guild_id -> user_id -> list of (hash, timestamp))
        self._image_hashes: Dict[int, Dict[int, List[Tuple[str, datetime]]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # User reputation cache (guild_id -> user_id -> reputation score)
        self._reputation_cache: Dict[int, Dict[int, float]] = defaultdict(dict)

        # Per-channel threshold overrides (channel_id -> multiplier)
        self._channel_multipliers: Dict[int, float] = {}

        # Exempt channels and roles
        self._exempt_channels: Set[int] = set()
        self._exempt_roles: Set[int] = set()

        # Regex patterns
        self._link_pattern = re.compile(
            r'https?://[^\s<>"{}|\\^`\[\]]+'
        )
        self._emoji_pattern = re.compile(
            r'<a?:\w+:\d+>|[\U0001F300-\U0001F9FF]'
        )
        self._char_repeat_pattern = re.compile(
            r'(.)\1{' + str(CHAR_REPEAT_LIMIT - 1) + r',}'
        )
        self._crypto_wallet_pattern = re.compile(CRYPTO_WALLET_PATTERN)

        self._load_exemptions()
        self._load_channel_multipliers()
        self._start_cleanup_task()
        self._start_reputation_task()

        logger.tree("Anti-Spam Service Loaded (Enhanced)", [
            ("Flood Limit", f"{FLOOD_MESSAGE_LIMIT} msgs / {FLOOD_TIME_WINDOW}s"),
            ("Duplicate Limit", f"{DUPLICATE_LIMIT}x @ {int(DUPLICATE_SIMILARITY_THRESHOLD*100)}% match"),
            ("Invite Detection", "Enabled with whitelist"),
            ("Reputation System", "Enabled"),
            ("Image Hashing", "Enabled"),
            ("Raid Detection", "Enhanced"),
            ("Webhook Protection", "Enabled"),
        ], emoji="🛡️")

    def _load_exemptions(self) -> None:
        """Load exempt channels and roles from config."""
        # Exempt prison channels (already restricted)
        if self.config.prison_channel_ids:
            self._exempt_channels.update(self.config.prison_channel_ids)

        # Exempt log channels
        if self.config.logs_channel_id:
            self._exempt_channels.add(self.config.logs_channel_id)
        if self.config.server_logs_forum_id:
            self._exempt_channels.add(self.config.server_logs_forum_id)

        # Exempt moderation role
        if self.config.moderation_role_id:
            self._exempt_roles.add(self.config.moderation_role_id)

    def _load_channel_multipliers(self) -> None:
        """Load per-channel threshold multipliers."""
        # This could be loaded from config/database
        # For now, we'll detect based on channel name patterns
        pass

    def _get_channel_multiplier(self, channel: discord.abc.GuildChannel) -> float:
        """Get threshold multiplier for a channel."""
        if channel.id in self._channel_multipliers:
            return self._channel_multipliers[channel.id]

        # Auto-detect based on channel name
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

        return 1.0  # Default

    def _start_cleanup_task(self) -> None:
        """Start background task to clean old message records."""
        create_safe_task(self._cleanup_loop(), "AntiSpam Cleanup Loop")

    def _start_reputation_task(self) -> None:
        """Start background task to update reputation scores."""
        create_safe_task(self._reputation_loop(), "AntiSpam Reputation Loop")

    async def _cleanup_loop(self) -> None:
        """Periodically clean up old message records and decay DB violations."""
        while True:
            await asyncio.sleep(MESSAGE_HISTORY_CLEANUP)
            try:
                self._cleanup_old_records()
                # Decay violations in database
                decayed = self.db.decay_spam_violations(VIOLATION_DECAY_TIME)
                if decayed > 0:
                    logger.debug(f"Decayed {decayed} spam violation records")
            except Exception as e:
                logger.warning(f"Anti-spam cleanup error: {e}")

    async def _reputation_loop(self) -> None:
        """Periodically update reputation scores for active users."""
        while True:
            await asyncio.sleep(REPUTATION_UPDATE_INTERVAL)
            try:
                await self._update_reputations()
            except Exception as e:
                logger.warning(f"Reputation update error: {e}")

    async def _update_reputations(self) -> None:
        """Update reputation for all tracked users."""
        # This would typically update the database
        # For now, we just clear the cache to force re-computation
        self._reputation_cache.clear()

    def _cleanup_old_records(self) -> None:
        """Remove old message records from memory."""
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
        for guild_id, guild_states in self._user_states.items():
            for user_id, state in list(guild_states.items()):
                state.messages = [
                    m for m in state.messages
                    if m.timestamp > cutoff
                ]
                if not state.messages:
                    del guild_states[user_id]

            # Enforce max users per guild limit
            if len(guild_states) > MAX_TRACKED_USERS_PER_GUILD:
                # Remove oldest entries (users with oldest last message)
                sorted_users = sorted(
                    guild_states.items(),
                    key=lambda x: x[1].messages[-1].timestamp if x[1].messages else cutoff
                )
                excess = len(guild_states) - MAX_TRACKED_USERS_PER_GUILD
                for user_id, _ in sorted_users[:excess]:
                    del guild_states[user_id]
                logger.debug(f"Anti-spam: Evicted {excess} oldest users from guild {guild_id}")

        # Clean image hashes
        image_cutoff = now - timedelta(seconds=IMAGE_DUPLICATE_TIME_WINDOW * 2)
        for guild_hashes in self._image_hashes.values():
            for user_id, hashes in list(guild_hashes.items()):
                guild_hashes[user_id] = [
                    (h, t) for h, t in hashes if t > image_cutoff
                ]
                if not guild_hashes[user_id]:
                    del guild_hashes[user_id]

        # Clean webhook states
        webhook_cutoff = now - timedelta(seconds=WEBHOOK_TIME_WINDOW * 2)
        for webhook_id, state in list(self._webhook_states.items()):
            state.messages = [t for t in state.messages if t > webhook_cutoff]
            if not state.messages:
                try:
                    del self._webhook_states[webhook_id]
                except KeyError:
                    pass  # Already removed

        # Clean old join records
        join_cutoff = now - timedelta(seconds=RAID_TIME_WINDOW * 2)
        for guild_id in list(self._recent_joins.keys()):
            self._recent_joins[guild_id] = [
                j for j in self._recent_joins[guild_id]
                if j.join_time > join_cutoff
            ]
            if not self._recent_joins[guild_id]:
                try:
                    del self._recent_joins[guild_id]
                except KeyError:
                    pass  # Already removed

    # =========================================================================
    # Reputation System
    # =========================================================================

    def get_user_reputation(self, user_id: int, guild_id: int) -> float:
        """Get user's reputation score."""
        # Check cache first
        if guild_id in self._reputation_cache:
            if user_id in self._reputation_cache[guild_id]:
                return self._reputation_cache[guild_id][user_id]

        # Calculate from database
        reputation = self._calculate_reputation(user_id, guild_id)
        self._reputation_cache[guild_id][user_id] = reputation
        return reputation

    def _calculate_reputation(self, user_id: int, guild_id: int) -> float:
        """Calculate reputation score from database."""
        # Get user data from database
        reputation = 0.0

        # Base reputation from account/server age
        try:
            user_info = self.db.get_user_join_info(user_id, guild_id)
            if user_info:
                join_timestamp = user_info.get("joined_at", 0)
                if join_timestamp:
                    days_in_server = (time.time() - join_timestamp) / 86400
                    reputation += min(days_in_server * 0.5, 50)  # Max 50 from tenure
        except Exception:
            pass

        # Subtract for violations
        violations = self.db.get_spam_violations(user_id, guild_id)
        if violations:
            total_violations = violations.get("total_violations", 0)
            reputation -= total_violations * REP_LOSS_WARNING

        # Get warning count
        try:
            warnings = self.db.get_user_warnings(user_id, guild_id)
            if warnings:
                reputation -= len(warnings) * REP_LOSS_WARNING
        except Exception:
            pass

        # Clamp to reasonable range
        return max(0, min(reputation, REPUTATION_VETERAN * 2))

    def _get_reputation_multiplier(self, user_id: int, guild_id: int) -> float:
        """Get threshold multiplier based on user reputation."""
        reputation = self.get_user_reputation(user_id, guild_id)

        if reputation >= REPUTATION_VETERAN:
            return REPUTATION_MULTIPLIERS[REPUTATION_VETERAN]
        elif reputation >= REPUTATION_TRUSTED:
            return REPUTATION_MULTIPLIERS[REPUTATION_TRUSTED]
        elif reputation >= REPUTATION_REGULAR:
            return REPUTATION_MULTIPLIERS[REPUTATION_REGULAR]
        else:
            return REPUTATION_MULTIPLIERS[REPUTATION_NEW]

    def update_reputation(self, user_id: int, guild_id: int, delta: float) -> None:
        """Update user's reputation score."""
        current = self.get_user_reputation(user_id, guild_id)
        new_rep = max(0, current + delta)
        self._reputation_cache[guild_id][user_id] = new_rep
        # Persist to database would go here

    # =========================================================================
    # Exemption Checks
    # =========================================================================

    def _is_exempt(self, message: discord.Message) -> bool:
        """Check if message/user is exempt from spam detection."""
        # Bots are exempt (but webhooks are checked separately)
        if message.author.bot and not message.webhook_id:
            return True

        # Check exempt channels
        if message.channel.id in self._exempt_channels:
            return True

        # Check exempt roles
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.id in self._exempt_roles:
                    return True

            # Admins are exempt
            if message.author.guild_permissions.administrator:
                return True

        return False

    # =========================================================================
    # Detection Helpers
    # =========================================================================

    def _count_emojis(self, content: str) -> int:
        """Count emojis in message content."""
        return len(self._emoji_pattern.findall(content))

    def _count_links(self, content: str) -> int:
        """Count links in message content."""
        return len(self._link_pattern.findall(content))

    def _count_newlines(self, content: str) -> int:
        """Count newlines in message content."""
        return content.count('\n')

    def _is_arabic_char(self, char: str) -> bool:
        """Check if a character is Arabic."""
        return ord(char) in ARABIC_RANGE if char else False

    def _is_new_member(self, member: discord.Member) -> bool:
        """Check if member is new (stricter spam rules apply)."""
        now = datetime.now(NY_TZ)

        # Check account age
        if member.created_at:
            account_age = (now - member.created_at.replace(tzinfo=NY_TZ)).days
            if account_age < NEW_MEMBER_ACCOUNT_AGE:
                return True

        # Check server join date
        if member.joined_at:
            server_age = (now - member.joined_at.replace(tzinfo=NY_TZ)).days
            if server_age < NEW_MEMBER_SERVER_AGE:
                return True

        return False

    def _strip_arabic_tashkeel(self, text: str) -> str:
        """Remove Arabic diacritical marks (tashkeel) from text."""
        return ''.join(c for c in text if c not in ARABIC_TASHKEEL)

    def _is_exempt_greeting(self, text: str) -> bool:
        """Check if text is a common Arabic/Islamic greeting (always exempt)."""
        if not text:
            return False
        # Normalize: strip whitespace, punctuation, and tashkeel
        normalized = text.strip().rstrip('!.،؟؛:')
        normalized = self._strip_arabic_tashkeel(normalized)
        return normalized in EXEMPT_ARABIC_GREETINGS

    def _is_mostly_arabic(self, text: str) -> bool:
        """Check if text is mostly Arabic (exempt from some spam checks)."""
        if not text:
            return False
        arabic_chars = sum(1 for c in text if ord(c) in ARABIC_RANGE)
        total_letters = sum(1 for c in text if c.isalpha())
        if total_letters == 0:
            return False
        # Lenient threshold - 30% Arabic is enough to be considered Arabic text
        # This catches Quran verses that may have translations mixed in
        return (arabic_chars / total_letters) >= 0.3

    def _is_emoji_only(self, text: str) -> bool:
        """Check if message is mostly emojis (exempt from duplicate detection)."""
        if not text:
            return False
        # Remove custom Discord emojis <:name:id> and <a:name:id>
        text_no_custom = re.sub(r'<a?:\w+:\d+>', '', text)
        # Remove standard Unicode emojis
        text_no_emoji = self._emoji_pattern.sub('', text_no_custom)
        # Remove whitespace
        text_clean = text_no_emoji.strip()
        # If nothing left (or very little), it's emoji-only
        return len(text_clean) < 10

    def _has_char_repeat(self, content: str) -> bool:
        """Check for repeated characters (excluding Arabic)."""
        match = self._char_repeat_pattern.search(content)
        if not match:
            return False
        repeated_char = match.group(1)
        if self._is_arabic_char(repeated_char):
            return False
        return True

    def _get_caps_percentage(self, content: str) -> float:
        """Get percentage of capital letters in content."""
        letters = [c for c in content if c.isalpha()]
        if len(letters) < CAPS_MIN_LENGTH:
            return 0
        caps = sum(1 for c in letters if c.isupper())
        return (caps / len(letters)) * 100

    def _is_similar(self, text1: str, text2: str) -> bool:
        """Check if two texts are similar using fuzzy matching."""
        if not text1 or not text2:
            return False
        ratio = SequenceMatcher(None, text1, text2).ratio()
        return ratio >= DUPLICATE_SIMILARITY_THRESHOLD

    def _count_combining_chars(self, content: str) -> int:
        """Count Unicode combining characters (used in Zalgo text), excluding Arabic tashkeel."""
        count = 0
        for c in content:
            if unicodedata.category(c) == 'Mn':
                # Exclude Arabic tashkeel/diacritical marks (U+064B to U+0670)
                if c not in ARABIC_TASHKEEL:
                    count += 1
        return count

    def _is_zalgo(self, content: str) -> bool:
        """Check if text contains Zalgo/excessive combining characters."""
        # Skip Zalgo check entirely for Arabic text (Quran verses have lots of tashkeel)
        if self._is_mostly_arabic(content):
            return False
        return self._count_combining_chars(content) >= ZALGO_COMBINING_LIMIT

    def _is_scam(self, content: str) -> bool:
        """Check if message contains scam/phishing patterns."""
        content_lower = content.lower()

        # Check scam phrases
        for phrase in SCAM_PHRASES:
            if phrase in content_lower:
                return True

        # Check phishing domains
        for domain in PHISHING_DOMAINS:
            if domain in content_lower:
                return True

        # Check crypto wallet + suspicious context
        if self._crypto_wallet_pattern.search(content):
            suspicious_words = ["send", "gift", "free", "claim", "win", "airdrop"]
            if any(word in content_lower for word in suspicious_words):
                return True

        return False

    # =========================================================================
    # Invite Detection
    # =========================================================================

    def _extract_invites(self, content: str) -> List[str]:
        """Extract Discord invite codes from message."""
        matches = DISCORD_INVITE_PATTERN.findall(content)
        return matches

    def _is_whitelisted_invite(self, invite_code: str) -> bool:
        """Check if invite code is whitelisted."""
        return invite_code.lower() in WHITELISTED_INVITE_CODES

    def _check_invite_spam(self, content: str, state: UserSpamState, now: datetime) -> bool:
        """Check if message contains non-whitelisted invite spam."""
        invites = self._extract_invites(content)
        if not invites:
            return False

        # Filter out whitelisted invites
        non_whitelisted = [i for i in invites if not self._is_whitelisted_invite(i)]
        if not non_whitelisted:
            return False

        # Track invites
        if state.last_invite_time and (now - state.last_invite_time).total_seconds() < INVITE_TIME_WINDOW:
            state.invite_count += len(non_whitelisted)
        else:
            state.invite_count = len(non_whitelisted)
        state.last_invite_time = now

        return state.invite_count >= INVITE_LIMIT

    # =========================================================================
    # Image Hash Detection
    # =========================================================================

    def _hash_attachment(self, attachment: discord.Attachment) -> str:
        """Generate a hash for an attachment based on URL and size."""
        # Use URL + size as a simple hash (actual perceptual hash would need image download)
        data = f"{attachment.filename}:{attachment.size}:{attachment.content_type}"
        return hashlib.md5(data.encode()).hexdigest()[:16]

    def _check_image_duplicate(
        self,
        message: discord.Message,
        now: datetime,
    ) -> bool:
        """Check if user is posting duplicate images."""
        if not message.attachments:
            return False

        guild_id = message.guild.id
        user_id = message.author.id

        # Hash current attachments
        current_hashes = [
            self._hash_attachment(a) for a in message.attachments
            if a.content_type and a.content_type.startswith("image/")
        ]

        if not current_hashes:
            return False

        # Check against recent hashes
        user_hashes = self._image_hashes[guild_id][user_id]
        cutoff = now - timedelta(seconds=IMAGE_DUPLICATE_TIME_WINDOW)

        for current_hash in current_hashes:
            match_count = sum(
                1 for h, t in user_hashes
                if h == current_hash and t > cutoff
            )
            if match_count >= IMAGE_DUPLICATE_LIMIT - 1:  # -1 because we're about to add this one
                return True

        # Add current hashes to tracking
        for h in current_hashes:
            user_hashes.append((h, now))

        return False

    # =========================================================================
    # Webhook Spam Detection
    # =========================================================================

    def _check_webhook_spam(self, message: discord.Message, now: datetime) -> bool:
        """Check if webhook is spamming."""
        if not message.webhook_id:
            return False

        state = self._webhook_states[message.webhook_id]
        cutoff = now - timedelta(seconds=WEBHOOK_TIME_WINDOW)

        # Clean old messages
        state.messages = [t for t in state.messages if t > cutoff]

        # Add current message
        state.messages.append(now)

        return len(state.messages) > WEBHOOK_MESSAGE_LIMIT

    # =========================================================================
    # Main Spam Detection
    # =========================================================================

    async def check_message(self, message: discord.Message) -> Optional[str]:
        """
        Check a message for spam.

        Args:
            message: The message to check.

        Returns:
            Spam type string if spam detected, None otherwise.
        """
        if self._is_exempt(message):
            return None

        if not message.guild:
            return None

        guild_id = message.guild.id
        user_id = message.author.id
        now = datetime.now(NY_TZ)

        # Check webhook spam first (different handling)
        if message.webhook_id:
            if self._check_webhook_spam(message, now):
                return "webhook_spam"
            return None  # Webhooks only checked for spam volume

        state = self._user_states[guild_id][user_id]

        # Create message record
        content = message.content or ""
        invites = self._extract_invites(content)

        record = MessageRecord(
            content=content.lower().strip(),
            timestamp=now,
            has_links=bool(self._link_pattern.search(content)),
            has_attachments=len(message.attachments) > 0,
            has_invites=bool(invites),
            mention_count=len(message.mentions) + len(message.role_mentions),
            emoji_count=self._count_emojis(content),
            attachment_hashes=[self._hash_attachment(a) for a in message.attachments],
        )

        state.messages.append(record)

        # Get multipliers for dynamic thresholds
        is_new = isinstance(message.author, discord.Member) and self._is_new_member(message.author)
        rep_multiplier = self._get_reputation_multiplier(user_id, guild_id)
        channel_multiplier = self._get_channel_multiplier(message.channel)
        total_multiplier = rep_multiplier * channel_multiplier

        # Set thresholds based on member status and multipliers
        if is_new:
            flood_limit = int(NEW_MEMBER_FLOOD_LIMIT * total_multiplier)
            duplicate_limit = int(NEW_MEMBER_DUPLICATE_LIMIT * total_multiplier)
            mention_limit = int(NEW_MEMBER_MENTION_LIMIT * total_multiplier)
        else:
            flood_limit = int(FLOOD_MESSAGE_LIMIT * total_multiplier)
            duplicate_limit = int(DUPLICATE_LIMIT * total_multiplier)
            mention_limit = int(MENTION_LIMIT * total_multiplier)

        # Ensure minimums
        flood_limit = max(flood_limit, 3)
        duplicate_limit = max(duplicate_limit, 2)
        mention_limit = max(mention_limit, 2)

        # Track channel messages for auto-slowmode
        await self._check_auto_slowmode(message)

        # Skip all spam checks for common Arabic/Islamic greetings
        if self._is_exempt_greeting(content):
            # Still give reputation boost for greetings
            self.update_reputation(user_id, guild_id, REP_GAIN_MESSAGE)
            return None

        # Check for various spam types (ordered by severity/frequency)
        spam_type = None

        # 1. Scam/Phishing (most dangerous - immediate action)
        if self._is_scam(content):
            spam_type = "scam"

        # 2. Zalgo/Unicode abuse (malicious)
        if not spam_type and self._is_zalgo(content):
            spam_type = "zalgo"

        # 3. Invite spam (high priority)
        if not spam_type and self._check_invite_spam(content, state, now):
            spam_type = "invite_spam"

        # 4. Message flood
        if not spam_type:
            recent_messages = [
                m for m in state.messages
                if (now - m.timestamp).total_seconds() < FLOOD_TIME_WINDOW
            ]
            if len(recent_messages) > flood_limit:
                spam_type = "message_flood"

        # 5. Duplicate spam (fuzzy matching) - skip short messages, Arabic text, and emoji-only
        is_arabic = self._is_mostly_arabic(content)
        is_emoji_only = self._is_emoji_only(content)
        if not spam_type and record.content and len(record.content) >= DUPLICATE_MIN_LENGTH and not is_arabic and not is_emoji_only:
            similar_count = 0
            for m in state.messages:
                if m is not record and (now - m.timestamp).total_seconds() < DUPLICATE_TIME_WINDOW:
                    if self._is_similar(m.content, record.content):
                        similar_count += 1
            if similar_count >= duplicate_limit - 1:
                spam_type = "duplicate"

        # 6. Image duplicate
        if not spam_type and self._check_image_duplicate(message, now):
            spam_type = "image_duplicate"

        # 7. Mention spam
        if not spam_type and record.mention_count >= mention_limit:
            spam_type = "mention_spam"

        # 8. Emoji spam
        emoji_limit = int(EMOJI_LIMIT * total_multiplier)
        if not spam_type and record.emoji_count >= emoji_limit:
            spam_type = "emoji_spam"

        # 9. Newline spam - skip Arabic text (Quran verses)
        newline_limit = int(NEWLINE_LIMIT * total_multiplier)
        if not spam_type and not is_arabic and self._count_newlines(content) >= newline_limit:
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

        # If no spam, give small reputation boost
        if not spam_type:
            self.update_reputation(user_id, guild_id, REP_GAIN_MESSAGE)

        return spam_type

    # =========================================================================
    # Enhanced Raid Detection
    # =========================================================================

    async def check_raid(self, member: discord.Member) -> Tuple[bool, Optional[str]]:
        """
        Check if a member join is part of a raid.

        Args:
            member: The member who joined.

        Returns:
            Tuple of (is_raid, raid_type)
        """
        if not member.guild:
            return False, None

        guild_id = member.guild.id
        now = datetime.now(NY_TZ)

        # Create join record
        account_created = member.created_at.replace(tzinfo=NY_TZ) if member.created_at else now
        has_default = member.avatar is None
        avatar_hash = str(member.avatar.key) if member.avatar else None

        record = JoinRecord(
            user_id=member.id,
            username=member.name,
            display_name=member.display_name,
            account_created=account_created,
            has_default_avatar=has_default,
            avatar_hash=avatar_hash,
            join_time=now,
        )

        self._recent_joins[guild_id].append(record)

        # Clean old joins
        cutoff = now - timedelta(seconds=RAID_TIME_WINDOW)
        self._recent_joins[guild_id] = [
            j for j in self._recent_joins[guild_id] if j.join_time > cutoff
        ]

        recent = self._recent_joins[guild_id]

        # Basic raid detection: too many new accounts joining
        new_accounts = [
            j for j in recent
            if (now - j.account_created).total_seconds() < RAID_ACCOUNT_AGE_HOURS * 3600
        ]

        # Weight default avatars more heavily
        weighted_count = sum(
            RAID_DEFAULT_AVATAR_WEIGHT if j.has_default_avatar else 1
            for j in new_accounts
        )

        if weighted_count >= RAID_JOIN_LIMIT:
            return True, "new_accounts"

        # Enhanced: Check for similar usernames
        if len(recent) >= 3:
            similar_names = 0
            for i, j1 in enumerate(recent):
                for j2 in recent[i+1:]:
                    name_sim = SequenceMatcher(None, j1.username.lower(), j2.username.lower()).ratio()
                    if name_sim >= RAID_SIMILAR_NAME_THRESHOLD:
                        similar_names += 1

            if similar_names >= 3:
                return True, "similar_names"

        # Enhanced: Check for accounts created at similar times
        if len(new_accounts) >= 3:
            creation_times = sorted([j.account_created for j in new_accounts])
            for i in range(len(creation_times) - 2):
                time_diff = (creation_times[i+2] - creation_times[i]).total_seconds()
                if time_diff <= RAID_SIMILAR_CREATION_WINDOW:
                    return True, "similar_creation"

        # Enhanced: Check for same avatar hash
        if len(recent) >= 3:
            avatar_counts = defaultdict(int)
            for j in recent:
                if j.avatar_hash:
                    avatar_counts[j.avatar_hash] += 1
            for count in avatar_counts.values():
                if count >= 3:
                    return True, "same_avatar"

        return False, None

    # =========================================================================
    # Auto-Slowmode
    # =========================================================================

    async def _check_auto_slowmode(self, message: discord.Message) -> None:
        """
        Check if channel needs auto-slowmode due to message flood.
        """
        if not message.guild or not isinstance(message.channel, discord.TextChannel):
            return

        channel_id = message.channel.id
        now = datetime.now(NY_TZ)

        # Check cooldown
        if channel_id in self._slowmode_cooldowns:
            cooldown_end = self._slowmode_cooldowns[channel_id] + timedelta(seconds=SLOWMODE_COOLDOWN)
            if now < cooldown_end:
                return

        # Track message
        self._channel_messages[channel_id].append(now)

        # Clean old messages
        cutoff = now - timedelta(seconds=SLOWMODE_TIME_WINDOW)
        self._channel_messages[channel_id] = [
            t for t in self._channel_messages[channel_id] if t > cutoff
        ]

        # Check if slowmode should trigger
        if len(self._channel_messages[channel_id]) >= SLOWMODE_TRIGGER_MESSAGES:
            await self._apply_slowmode(message.channel)
            self._slowmode_cooldowns[channel_id] = now
            self._channel_messages[channel_id] = []

    async def _apply_slowmode(self, channel: discord.TextChannel) -> None:
        """Apply temporary slowmode to a channel."""
        try:
            original_slowmode = channel.slowmode_delay
            await channel.edit(slowmode_delay=SLOWMODE_DURATION)

            embed = discord.Embed(
                title="🐌 Slowmode Enabled",
                description=f"Auto-slowmode activated due to high message volume.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Duration", value=f"{SLOWMODE_DURATION}s", inline=True)
            embed.add_field(name="Reason", value="Spam wave detected", inline=True)
            set_footer(embed)

            await channel.send(embed=embed, delete_after=30)

            logger.tree("AUTO-SLOWMODE ENABLED", [
                ("Channel", f"#{channel.name}"),
                ("Duration", f"{SLOWMODE_DURATION}s"),
            ], emoji="🐌")

            await asyncio.sleep(SLOWMODE_DURATION)

            try:
                await channel.edit(slowmode_delay=original_slowmode)
                logger.tree("AUTO-SLOWMODE DISABLED", [
                    ("Channel", f"#{channel.name}"),
                ], emoji="🐌")
            except discord.HTTPException:
                pass

        except discord.Forbidden:
            logger.warning(f"Cannot set slowmode in #{channel.name} - missing permissions")
        except discord.HTTPException as e:
            logger.warning(f"Failed to set slowmode: {e}")

    # =========================================================================
    # Punishment Handling
    # =========================================================================

    async def handle_spam(
        self,
        message: discord.Message,
        spam_type: str,
    ) -> None:
        """
        Handle a detected spam message.
        """
        if not message.guild or not isinstance(message.author, discord.Member):
            return

        guild_id = message.guild.id
        user_id = message.author.id

        # Add violation to database
        violation_count = self.db.add_spam_violation(user_id, guild_id, spam_type)

        # Reduce reputation
        self.update_reputation(user_id, guild_id, -REP_LOSS_WARNING)

        # Delete the spam message
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        # Determine punishment
        mute_level = min(violation_count, 5)
        mute_duration = MUTE_DURATIONS.get(mute_level, 86400)

        # Format spam type for display
        spam_display = {
            "scam": "Scam/Phishing",
            "message_flood": "Message Flooding",
            "duplicate": "Duplicate Messages",
            "image_duplicate": "Duplicate Images",
            "mention_spam": "Mention Spam",
            "emoji_spam": "Emoji Spam",
            "link_flood": "Link Spam",
            "invite_spam": "Invite Spam",
            "caps_spam": "Caps Spam",
            "newline_spam": "Newline Spam",
            "char_spam": "Character Spam",
            "attachment_flood": "Attachment Spam",
            "zalgo": "Zalgo/Unicode Abuse",
            "webhook_spam": "Webhook Spam",
        }.get(spam_type, spam_type)

        if mute_duration == 0:
            await self._send_warning(message.author, spam_display, message.channel)
            await self._log_spam(message, spam_type, "warning", violation_count)
        else:
            self.update_reputation(user_id, guild_id, -REP_LOSS_MUTE)
            await self._apply_mute(
                message.author,
                mute_duration,
                spam_display,
                message.channel,
                violation_count,
            )
            await self._log_spam(message, spam_type, "mute", violation_count, mute_duration)

    async def handle_webhook_spam(self, message: discord.Message) -> None:
        """Handle spam from a webhook."""
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        logger.tree("WEBHOOK SPAM DETECTED", [
            ("Webhook ID", str(message.webhook_id)),
            ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "Unknown"),
            ("Action", "Message deleted"),
        ], emoji="🛡️")

        # Log to server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                embed = discord.Embed(
                    title="🛡️ Webhook Spam Detected",
                    color=EmbedColors.WARNING,
                    timestamp=datetime.now(NY_TZ),
                )
                embed.add_field(name="Webhook ID", value=str(message.webhook_id), inline=True)
                embed.add_field(
                    name="Channel",
                    value=f"<#{message.channel.id}>",
                    inline=True
                )
                embed.add_field(name="Action", value="Message deleted", inline=True)

                await self.bot.logging_service._send_log(
                    self.bot.logging_service.LogCategory.ALERTS,
                    embed,
                )
            except Exception:
                pass

    async def _send_warning(
        self,
        member: discord.Member,
        spam_type: str,
        channel: discord.abc.Messageable,
    ) -> None:
        """Send a warning embed to the user."""
        try:
            embed = discord.Embed(
                title="⚠️ Spam Warning",
                description=f"{member.mention}, please don't spam.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Reason", value=spam_type, inline=True)
            embed.add_field(name="Action", value="Message deleted", inline=True)
            set_footer(embed)

            await channel.send(embed=embed, delete_after=10)
        except discord.HTTPException:
            pass

    async def _apply_mute(
        self,
        member: discord.Member,
        duration: int,
        spam_type: str,
        channel: discord.abc.Messageable,
        violation_count: int,
    ) -> None:
        """Apply mute role to the user."""
        if not self.config.muted_role_id:
            return

        mute_role = member.guild.get_role(self.config.muted_role_id)
        if not mute_role:
            return

        try:
            await member.add_roles(
                mute_role,
                reason=f"Anti-spam: {spam_type} (violation #{violation_count})",
            )

            if duration >= 3600:
                duration_str = f"{duration // 3600}h"
            else:
                duration_str = f"{duration // 60}m"

            expires_at = datetime.now(NY_TZ) + timedelta(seconds=duration)
            self.db.add_mute(
                user_id=member.id,
                guild_id=member.guild.id,
                expires_at=expires_at.timestamp(),
                reason=f"Auto-spam: {spam_type}",
            )

            case_info = await self._open_spam_case(member, spam_type, duration, violation_count)

            embed = discord.Embed(
                title="🔇 Auto-Muted",
                description=f"{member.mention} has been muted for spamming.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Reason", value=spam_type, inline=True)
            embed.add_field(name="Duration", value=duration_str, inline=True)
            embed.add_field(name="Violation", value=f"#{violation_count}", inline=True)
            set_footer(embed)

            view = None
            if case_info and case_info.get("thread_id"):
                case_url = f"https://discord.com/channels/{member.guild.id}/{case_info['thread_id']}"
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(
                    label="Case",
                    url=case_url,
                    style=discord.ButtonStyle.link,
                    emoji=CASE_EMOJI,
                ))

            await channel.send(embed=embed, view=view, delete_after=15)

        except discord.Forbidden:
            logger.warning(f"Cannot mute {member} - missing permissions")
        except discord.HTTPException as e:
            logger.warning(f"Failed to mute {member}: {e}")

    async def _open_spam_case(
        self,
        member: discord.Member,
        spam_type: str,
        duration: int,
        violation_count: int,
    ) -> Optional[dict]:
        """Open a case for the spam violation and return case info."""
        if not self.bot.case_log_service:
            return None

        if duration >= 3600:
            duration_str = f"{duration // 3600} hour(s)"
        else:
            duration_str = f"{duration // 60} minute(s)"

        try:
            case_info = await asyncio.wait_for(
                self.bot.case_log_service.log_mute(
                    user=member,
                    moderator=self.bot.user,
                    duration=duration_str,
                    reason=f"Auto-spam detection: {spam_type} (violation #{violation_count})",
                    is_extension=False,
                    evidence=None,
                ),
                timeout=10.0,
            )
            return case_info
        except asyncio.TimeoutError:
            logger.warning("Case Log Timeout", [
                ("Action", "Auto-Spam Mute"),
                ("User", f"{member} ({member.id})"),
            ])
            return None
        except Exception as e:
            logger.error("Case Log Failed", [
                ("Action", "Auto-Spam Mute"),
                ("User", f"{member} ({member.id})"),
                ("Error", str(e)[:100]),
            ])
            return None

    async def _log_spam(
        self,
        message: discord.Message,
        spam_type: str,
        action: str,
        violation_count: int,
        mute_duration: int = 0,
    ) -> None:
        """Log spam incident to server logs."""
        spam_display = {
            "scam": "Scam/Phishing",
            "message_flood": "Message Flooding",
            "duplicate": "Duplicate Messages",
            "image_duplicate": "Duplicate Images",
            "mention_spam": "Mention Spam",
            "emoji_spam": "Emoji Spam",
            "link_flood": "Link Spam",
            "invite_spam": "Invite Spam",
            "caps_spam": "Caps Spam",
            "newline_spam": "Newline Spam",
            "char_spam": "Character Spam",
            "attachment_flood": "Attachment Spam",
            "zalgo": "Zalgo/Unicode Abuse",
            "webhook_spam": "Webhook Spam",
        }.get(spam_type, spam_type)

        action_str = "warned" if action == "warning" else f"muted ({mute_duration}s)"
        logger.tree("SPAM DETECTED", [
            ("User", f"{message.author} ({message.author.id})"),
            ("Type", spam_display),
            ("Action", action_str),
            ("Violations", str(violation_count)),
            ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "DM"),
        ], emoji="🛡️")

        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                if mute_duration > 0:
                    if mute_duration >= 3600:
                        duration_str = f"{mute_duration // 3600}h"
                    else:
                        duration_str = f"{mute_duration // 60}m"

                    embed = discord.Embed(
                        title="🛡️ Auto-Spam Mute",
                        color=EmbedColors.WARNING,
                        timestamp=datetime.now(NY_TZ),
                    )
                    embed.add_field(name="User", value=f"{message.author.mention}", inline=True)
                    embed.add_field(name="Type", value=spam_display, inline=True)
                    embed.add_field(name="Duration", value=duration_str, inline=True)
                    embed.add_field(name="Violations", value=f"#{violation_count}", inline=True)
                    if message.content:
                        content_preview = message.content[:100] + ("..." if len(message.content) > 100 else "")
                        embed.add_field(name="Content", value=f"```{content_preview}```", inline=False)

                    await self.bot.logging_service._send_log(
                        self.bot.logging_service.LogCategory.MOD_ACTIONS,
                        embed,
                    )
            except Exception as e:
                logger.debug(f"Failed to log spam to server logs: {e}")

    async def handle_raid(self, guild: discord.Guild, raid_type: str = "unknown") -> None:
        """Handle a detected raid by alerting mods."""
        raid_descriptions = {
            "new_accounts": "Multiple new accounts joined rapidly",
            "similar_names": "Multiple accounts with similar usernames joined",
            "similar_creation": "Multiple accounts created at similar times joined",
            "same_avatar": "Multiple accounts with identical avatars joined",
            "unknown": "Suspicious join pattern detected",
        }

        logger.tree("🚨 RAID DETECTED", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("Type", raid_type),
            ("Action", "Alert sent"),
        ], emoji="🚨")

        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                embed = discord.Embed(
                    title="🚨 Raid Detected",
                    description=raid_descriptions.get(raid_type, "Suspicious activity detected.") +
                                "\nConsider running `/lockdown`.",
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
                embed.add_field(name="Type", value=raid_type.replace("_", " ").title(), inline=True)
                embed.add_field(
                    name="Detected",
                    value=f"{RAID_JOIN_LIMIT}+ suspicious joins in {RAID_TIME_WINDOW}s",
                    inline=True,
                )

                await self.bot.logging_service._send_log(
                    self.bot.logging_service.LogCategory.ALERTS,
                    embed,
                )

                if self.config.developer_id:
                    thread = await self.bot.logging_service._get_or_create_thread(
                        self.bot.logging_service.LogCategory.ALERTS
                    )
                    if thread:
                        await thread.send(
                            f"<@{self.config.developer_id}> 🚨 **RAID DETECTED ({raid_type})!** "
                            f"Consider running `/lockdown`."
                        )
            except Exception as e:
                logger.debug(f"Failed to log raid: {e}")

        # Alert in mod channel if configured
        if self.config.alert_channel_id:
            try:
                alert_channel = self.bot.get_channel(self.config.alert_channel_id)
                if alert_channel:
                    embed = discord.Embed(
                        title="🚨 RAID ALERT",
                        description=raid_descriptions.get(raid_type, "Suspicious activity detected."),
                        color=EmbedColors.ERROR,
                        timestamp=datetime.now(NY_TZ),
                    )
                    embed.add_field(name="Type", value=raid_type.replace("_", " ").title(), inline=True)
                    embed.add_field(name="Action", value="Consider `/lockdown`", inline=True)

                    await alert_channel.send("@everyone", embed=embed)
            except Exception:
                pass


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AntiSpamService"]
