"""
Azab Discord Bot - Anti-Spam Service
=====================================

Automatic spam detection and prevention system.

DESIGN:
    Tracks message patterns per user and detects various spam types.
    Uses progressive punishment: warn → short mute → longer mute.
    Integrates with case logging and server logs.
    Persists violations to database (survives restarts).

Spam Types Detected:
    - Message flood: Too many messages too fast
    - Duplicate spam: Similar messages repeated (fuzzy matching)
    - Mention spam: Too many mentions
    - Emoji spam: Excessive emojis
    - Link flood: Multiple links in short time
    - Caps spam: Excessive capital letters
    - Newline spam: Excessive line breaks
    - Character spam: Repeated characters
    - Attachment flood: Too many attachments
    - Zalgo/Unicode abuse: Malicious unicode text

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants - Thresholds (Not Too Strict)
# =============================================================================

# Message flood: X messages in Y seconds (lenient for active chat)
FLOOD_MESSAGE_LIMIT = 8
FLOOD_TIME_WINDOW = 5  # seconds

# Duplicate spam: Similar messages X times in Y seconds
DUPLICATE_LIMIT = 4  # need 4 similar messages, not 3
DUPLICATE_TIME_WINDOW = 30  # seconds
DUPLICATE_SIMILARITY_THRESHOLD = 0.90  # 90% similar = duplicate (stricter matching)

# Mention spam: X mentions in one message
MENTION_LIMIT = 6

# Emoji spam: X emojis in one message
EMOJI_LIMIT = 20  # lenient for expressive chat

# Link flood: X links in Y seconds
LINK_LIMIT = 4
LINK_TIME_WINDOW = 30  # seconds

# Caps spam: X% caps in message with min length
CAPS_PERCENTAGE = 80
CAPS_MIN_LENGTH = 15

# Newline spam: X newlines in one message (high limit for Quran verses)
NEWLINE_LIMIT = 30

# Character spam: Same char repeated X+ times (lenient - only catches extreme cases)
CHAR_REPEAT_LIMIT = 30

# Arabic characters range (exempt from char spam and lenient on duplicates)
# Arabic script: U+0600 to U+06FF
ARABIC_RANGE = range(0x0600, 0x06FF + 1)

# Common Arabic/Islamic greetings (always exempt from spam detection)
EXEMPT_ARABIC_GREETINGS = {
    "السلام عليكم",
    "السلام عليكم ورحمة الله",
    "السلام عليكم ورحمة الله وبركاته",
    "وعليكم السلام",
    "وعليكم السلام ورحمة الله",
    "وعليكم السلام ورحمة الله وبركاته",
    "صباح الخير",
    "مساء الخير",
    "مرحبا",
    "اهلا",
    "اهلا وسهلا",
    "الحمد لله",
    "سبحان الله",
    "الله اكبر",
    "ماشاء الله",
    "استغفر الله",
    "بسم الله",
    "جزاك الله خيرا",
    "بارك الله فيك",
}

# Minimum length for duplicate detection (short messages ignored)
DUPLICATE_MIN_LENGTH = 80  # ignore short/casual repeated messages

# Attachment flood: X attachments in Y seconds
ATTACHMENT_LIMIT = 5
ATTACHMENT_TIME_WINDOW = 30  # seconds

# Zalgo detection: X+ combining characters
ZALGO_COMBINING_LIMIT = 10

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

# New account threshold for raids
NEW_ACCOUNT_DAYS = 7

# New member thresholds (stricter for accounts < 30 days or joined < 7 days)
NEW_MEMBER_ACCOUNT_AGE = 30  # days
NEW_MEMBER_SERVER_AGE = 7   # days
NEW_MEMBER_FLOOD_LIMIT = 5  # stricter than regular 8
NEW_MEMBER_DUPLICATE_LIMIT = 2  # stricter than regular 4
NEW_MEMBER_MENTION_LIMIT = 3  # stricter than regular 6

# Raid detection: X new accounts in Y seconds
RAID_JOIN_LIMIT = 5
RAID_TIME_WINDOW = 30  # seconds

# Auto-slowmode settings
SLOWMODE_TRIGGER_MESSAGES = 15  # Messages in time window to trigger slowmode
SLOWMODE_TIME_WINDOW = 10  # seconds
SLOWMODE_DURATION = 30  # seconds of slowmode
SLOWMODE_COOLDOWN = 300  # 5 minutes before slowmode can trigger again

# Cleanup intervals
MESSAGE_HISTORY_CLEANUP = 60  # seconds
VIOLATION_DECAY_TIME = 300  # 5 minutes - violations decay after this


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
    mention_count: int = 0
    emoji_count: int = 0


@dataclass
class UserSpamState:
    """Tracks spam state for a user (in-memory for recent messages)."""
    messages: List[MessageRecord] = field(default_factory=list)


# =============================================================================
# Anti-Spam Service
# =============================================================================

class AntiSpamService:
    """
    Automatic spam detection and prevention.

    Tracks message patterns and applies progressive punishment
    for spam violations. Violations are persisted to database.
    """

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # User state tracking for recent messages (guild_id -> user_id -> state)
        # NOTE: Violations are in database, this is just message history
        self._user_states: Dict[int, Dict[int, UserSpamState]] = defaultdict(
            lambda: defaultdict(UserSpamState)
        )

        # Recent joins for raid detection (guild_id -> list of join times)
        self._recent_joins: Dict[int, List[datetime]] = defaultdict(list)

        # Channel message tracking for auto-slowmode (channel_id -> list of timestamps)
        self._channel_messages: Dict[int, List[datetime]] = defaultdict(list)

        # Slowmode cooldowns (channel_id -> last slowmode time)
        self._slowmode_cooldowns: Dict[int, datetime] = {}

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
        self._start_cleanup_task()

        logger.tree("Anti-Spam Service Loaded", [
            ("Flood Limit", f"{FLOOD_MESSAGE_LIMIT} msgs / {FLOOD_TIME_WINDOW}s"),
            ("Duplicate Limit", f"{DUPLICATE_LIMIT}x @ {int(DUPLICATE_SIMILARITY_THRESHOLD*100)}% match"),
            ("Mention Limit", str(MENTION_LIMIT)),
            ("Persistence", "Database-backed"),
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

    def _start_cleanup_task(self) -> None:
        """Start background task to clean old message records."""
        asyncio.create_task(self._cleanup_loop())

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
                logger.debug(f"Anti-spam cleanup error: {e}")

    def _cleanup_old_records(self) -> None:
        """Remove old message records from memory."""
        now = datetime.now(NY_TZ)
        cutoff = now - timedelta(seconds=max(
            FLOOD_TIME_WINDOW,
            DUPLICATE_TIME_WINDOW,
            LINK_TIME_WINDOW,
            ATTACHMENT_TIME_WINDOW
        ) * 2)

        for guild_states in self._user_states.values():
            for user_id, state in list(guild_states.items()):
                # Remove old messages
                state.messages = [
                    m for m in state.messages
                    if m.timestamp > cutoff
                ]

                # Remove empty states
                if not state.messages:
                    del guild_states[user_id]

    def _is_exempt(self, message: discord.Message) -> bool:
        """Check if message/user is exempt from spam detection."""
        # Bots are exempt
        if message.author.bot:
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

    def _is_exempt_greeting(self, text: str) -> bool:
        """Check if text is a common Arabic/Islamic greeting (always exempt)."""
        if not text:
            return False
        # Normalize: strip whitespace and common punctuation
        normalized = text.strip().rstrip('!.،؟')
        return normalized in EXEMPT_ARABIC_GREETINGS

    def _is_mostly_arabic(self, text: str) -> bool:
        """Check if text is mostly Arabic (exempt from some spam checks)."""
        if not text:
            return False
        arabic_chars = sum(1 for c in text if ord(c) in ARABIC_RANGE)
        total_letters = sum(1 for c in text if c.isalpha())
        if total_letters == 0:
            return False
        return (arabic_chars / total_letters) >= 0.5  # 50%+ Arabic

    def _has_char_repeat(self, content: str) -> bool:
        """Check for repeated characters (excluding Arabic)."""
        match = self._char_repeat_pattern.search(content)
        if not match:
            return False
        # Allow all Arabic characters (lenient for Arabic text)
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
        """Count Unicode combining characters (used in Zalgo text)."""
        return sum(1 for c in content if unicodedata.category(c) == 'Mn')

    def _is_zalgo(self, content: str) -> bool:
        """Check if text contains Zalgo/excessive combining characters."""
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
    # Spam Detection
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

        state = self._user_states[guild_id][user_id]

        # Create message record
        content = message.content or ""
        record = MessageRecord(
            content=content.lower().strip(),
            timestamp=now,
            has_links=bool(self._link_pattern.search(content)),
            has_attachments=len(message.attachments) > 0,
            mention_count=len(message.mentions) + len(message.role_mentions),
            emoji_count=self._count_emojis(content),
        )

        state.messages.append(record)

        # Check if new member (stricter limits apply)
        is_new = isinstance(message.author, discord.Member) and self._is_new_member(message.author)

        # Set thresholds based on member status
        flood_limit = NEW_MEMBER_FLOOD_LIMIT if is_new else FLOOD_MESSAGE_LIMIT
        duplicate_limit = NEW_MEMBER_DUPLICATE_LIMIT if is_new else DUPLICATE_LIMIT
        mention_limit = NEW_MEMBER_MENTION_LIMIT if is_new else MENTION_LIMIT

        # Track channel messages for auto-slowmode
        await self._check_auto_slowmode(message)

        # Skip all spam checks for common Arabic/Islamic greetings
        if self._is_exempt_greeting(content):
            return None

        # Check for various spam types (ordered by severity/frequency)
        spam_type = None

        # 1. Scam/Phishing (most dangerous - immediate action)
        if self._is_scam(content):
            spam_type = "scam"

        # 2. Zalgo/Unicode abuse (malicious)
        if not spam_type and self._is_zalgo(content):
            spam_type = "zalgo"

        # 2. Message flood
        if not spam_type:
            recent_messages = [
                m for m in state.messages
                if (now - m.timestamp).total_seconds() < FLOOD_TIME_WINDOW
            ]
            if len(recent_messages) > flood_limit:
                spam_type = "message_flood"

        # 3. Duplicate spam (fuzzy matching) - skip short messages and Arabic text
        is_arabic = self._is_mostly_arabic(content)
        if not spam_type and record.content and len(record.content) >= DUPLICATE_MIN_LENGTH and not is_arabic:
            similar_count = 0
            for m in state.messages:
                if m is not record and (now - m.timestamp).total_seconds() < DUPLICATE_TIME_WINDOW:
                    if self._is_similar(m.content, record.content):
                        similar_count += 1
            if similar_count >= duplicate_limit - 1:  # -1 because we count matches, not including self
                spam_type = "duplicate"

        # 4. Mention spam
        if not spam_type and record.mention_count >= mention_limit:
            spam_type = "mention_spam"

        # 5. Emoji spam
        if not spam_type and record.emoji_count >= EMOJI_LIMIT:
            spam_type = "emoji_spam"

        # 6. Newline spam - skip Arabic text (Quran verses)
        if not spam_type and not is_arabic and self._count_newlines(content) >= NEWLINE_LIMIT:
            spam_type = "newline_spam"

        # 7. Character spam - DISABLED (too many false positives like "HIIIII" or "YESSSSS")
        # if not spam_type and self._has_char_repeat(content):
        #     spam_type = "char_spam"

        # 8. Link flood
        if not spam_type and record.has_links:
            recent_links = [
                m for m in state.messages
                if m.has_links
                and (now - m.timestamp).total_seconds() < LINK_TIME_WINDOW
            ]
            if len(recent_links) >= LINK_LIMIT:
                spam_type = "link_flood"

        # 9. Attachment flood
        if not spam_type and record.has_attachments:
            recent_attachments = [
                m for m in state.messages
                if m.has_attachments
                and (now - m.timestamp).total_seconds() < ATTACHMENT_TIME_WINDOW
            ]
            if len(recent_attachments) >= ATTACHMENT_LIMIT:
                spam_type = "attachment_flood"

        # 10. Caps spam - DISABLED (people use caps for emphasis/excitement)
        # if not spam_type and len(content) >= CAPS_MIN_LENGTH:
        #     if self._get_caps_percentage(content) >= CAPS_PERCENTAGE:
        #         spam_type = "caps_spam"

        return spam_type

    # =========================================================================
    # Raid Detection
    # =========================================================================

    async def check_raid(self, member: discord.Member) -> bool:
        """
        Check if a member join is part of a raid.

        Args:
            member: The member who joined.

        Returns:
            True if raid detected, False otherwise.
        """
        if not member.guild:
            return False

        guild_id = member.guild.id
        now = datetime.now(NY_TZ)

        # Check if new account
        if member.created_at:
            account_age = (now - member.created_at.replace(tzinfo=NY_TZ)).days
            if account_age > NEW_ACCOUNT_DAYS:
                return False  # Not a new account, less suspicious

        # Track join
        self._recent_joins[guild_id].append(now)

        # Clean old joins
        cutoff = now - timedelta(seconds=RAID_TIME_WINDOW)
        self._recent_joins[guild_id] = [
            t for t in self._recent_joins[guild_id] if t > cutoff
        ]

        # Check for raid
        if len(self._recent_joins[guild_id]) >= RAID_JOIN_LIMIT:
            return True

        return False

    # =========================================================================
    # Auto-Slowmode
    # =========================================================================

    async def _check_auto_slowmode(self, message: discord.Message) -> None:
        """
        Check if channel needs auto-slowmode due to message flood.

        Triggers slowmode when too many messages in a short time.
        Has a cooldown to prevent constant toggling.
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
            self._channel_messages[channel_id] = []  # Reset counter

    async def _apply_slowmode(self, channel: discord.TextChannel) -> None:
        """Apply temporary slowmode to a channel."""
        try:
            # Store original slowmode
            original_slowmode = channel.slowmode_delay

            # Apply slowmode
            await channel.edit(slowmode_delay=SLOWMODE_DURATION)

            # Send notification
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

            # Schedule removal
            await asyncio.sleep(SLOWMODE_DURATION)

            # Restore original slowmode
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

        Args:
            message: The spam message.
            spam_type: Type of spam detected.
        """
        if not message.guild or not isinstance(message.author, discord.Member):
            return

        guild_id = message.guild.id
        user_id = message.author.id

        # Add violation to database (persisted)
        violation_count = self.db.add_spam_violation(user_id, guild_id, spam_type)

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
            "mention_spam": "Mention Spam",
            "emoji_spam": "Emoji Spam",
            "link_flood": "Link Spam",
            "caps_spam": "Caps Spam",
            "newline_spam": "Newline Spam",
            "char_spam": "Character Spam",
            "attachment_flood": "Attachment Spam",
            "zalgo": "Zalgo/Unicode Abuse",
        }.get(spam_type, spam_type)

        if mute_duration == 0:
            # First offense: warning only
            await self._send_warning(message.author, spam_display, message.channel)
            await self._log_spam(message, spam_type, "warning", violation_count)
        else:
            # Mute the user
            await self._apply_mute(
                message.author,
                mute_duration,
                spam_display,
                message.channel,
                violation_count,
            )
            await self._log_spam(message, spam_type, "mute", violation_count, mute_duration)

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
            # Apply mute role
            await member.add_roles(
                mute_role,
                reason=f"Anti-spam: {spam_type} (violation #{violation_count})",
            )

            # Format duration
            if duration >= 3600:
                duration_str = f"{duration // 3600}h"
            else:
                duration_str = f"{duration // 60}m"

            # Store mute expiry in database for auto-unmute
            expires_at = datetime.now(NY_TZ) + timedelta(seconds=duration)
            self.db.add_mute(
                user_id=member.id,
                guild_id=member.guild.id,
                expires_at=expires_at.timestamp(),
                reason=f"Auto-spam: {spam_type}",
            )

            # Open a case first to get the thread ID
            case_info = await self._open_spam_case(member, spam_type, duration, violation_count)

            # Build public embed
            embed = discord.Embed(
                title="🔇 Auto-Muted",
                description=f"{member.mention} has been muted for spamming.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Reason", value=spam_type, inline=True)
            embed.add_field(name="Duration", value=duration_str, inline=True)
            embed.add_field(name="Violation", value=f"#{violation_count}", inline=True)
            set_footer(embed)

            # Add case button if case was created
            view = None
            if case_info and case_info.get("thread_id"):
                case_url = f"https://discord.com/channels/{member.guild.id}/{case_info['thread_id']}"
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(
                    label="Case",
                    url=case_url,
                    style=discord.ButtonStyle.link,
                    emoji="📋",
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

        # Format duration
        if duration >= 3600:
            duration_str = f"{duration // 3600} hour(s)"
        else:
            duration_str = f"{duration // 60} minute(s)"

        try:
            case_info = await self.bot.case_log_service.log_mute(
                user=member,
                moderator=self.bot.user,
                duration=duration_str,
                reason=f"Auto-spam detection: {spam_type} (violation #{violation_count})",
                is_extension=False,
                evidence=None,
            )
            return case_info
        except Exception as e:
            logger.warning(f"Failed to open spam case: {e}")
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
        # Format spam type for display
        spam_display = {
            "scam": "Scam/Phishing",
            "message_flood": "Message Flooding",
            "duplicate": "Duplicate Messages",
            "mention_spam": "Mention Spam",
            "emoji_spam": "Emoji Spam",
            "link_flood": "Link Spam",
            "caps_spam": "Caps Spam",
            "newline_spam": "Newline Spam",
            "char_spam": "Character Spam",
            "attachment_flood": "Attachment Spam",
            "zalgo": "Zalgo/Unicode Abuse",
        }.get(spam_type, spam_type)

        # Log to console
        action_str = "warned" if action == "warning" else f"muted ({mute_duration}s)"
        logger.tree("SPAM DETECTED", [
            ("User", f"{message.author} ({message.author.id})"),
            ("Type", spam_display),
            ("Action", action_str),
            ("Violations", str(violation_count)),
            ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "DM"),
        ], emoji="🛡️")

        # Log to server logs
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

    async def handle_raid(self, guild: discord.Guild) -> None:
        """Handle a detected raid by alerting mods."""
        logger.tree("RAID DETECTED", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("Action", "Alert sent"),
        ], emoji="🚨")

        # Log to server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                embed = discord.Embed(
                    title="🚨 Raid Detected",
                    description="Multiple new accounts joined rapidly. Consider running `/lockdown`.",
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
                embed.add_field(
                    name="Detected",
                    value=f"{RAID_JOIN_LIMIT}+ new accounts in {RAID_TIME_WINDOW}s",
                    inline=False,
                )

                await self.bot.logging_service._send_log(
                    self.bot.logging_service.LogCategory.ALERTS,
                    embed,
                )

                # Ping developer
                if self.config.developer_id:
                    thread = await self.bot.logging_service._get_or_create_thread(
                        self.bot.logging_service.LogCategory.ALERTS
                    )
                    if thread:
                        await thread.send(
                            f"<@{self.config.developer_id}> ⚠️ **Potential raid detected!** "
                            f"Consider running `/lockdown`."
                        )
            except Exception as e:
                logger.debug(f"Failed to log raid: {e}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AntiSpamService"]
