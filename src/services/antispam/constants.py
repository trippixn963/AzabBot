"""
Anti-Spam Constants
===================

All thresholds, patterns, limits, and configuration for spam detection.
"""

import re
from typing import Dict, FrozenSet, List, Set


# =============================================================================
# Message Flood
# =============================================================================

FLOOD_MESSAGE_LIMIT = 6  # 6 messages in 5 seconds = spam
FLOOD_TIME_WINDOW = 5  # seconds


# =============================================================================
# Duplicate Spam
# =============================================================================

DUPLICATE_LIMIT = 3  # 3 similar messages = spam
DUPLICATE_TIME_WINDOW = 30  # seconds
DUPLICATE_SIMILARITY_THRESHOLD = 0.85  # 85% similar = duplicate
DUPLICATE_MIN_LENGTH = 150  # ignore short/casual repeated messages


# =============================================================================
# Mention Spam
# =============================================================================

MENTION_LIMIT = 5


# =============================================================================
# Emoji Spam
# =============================================================================

EMOJI_LIMIT = 20  # reasonable for expressive chat


# =============================================================================
# Link Flood
# =============================================================================

LINK_LIMIT = 3
LINK_TIME_WINDOW = 30  # seconds

# Safe domains that don't count as spam links (media embeds, etc.)
SAFE_LINK_DOMAINS: Set[str] = {
    # GIF platforms
    "tenor.com",
    "giphy.com",
    "gfycat.com",
    "imgur.com",
    # Discord CDN
    "cdn.discordapp.com",
    "media.discordapp.net",
    # Image hosting
    "i.imgur.com",
    "i.redd.it",
    "preview.redd.it",
    # Video platforms (embeds)
    "youtube.com",
    "youtu.be",
    "twitch.tv",
    "clips.twitch.tv",
    # Social media (embeds)
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
}


# =============================================================================
# Invite Spam
# =============================================================================

INVITE_LIMIT = 1  # any invite is suspicious
INVITE_TIME_WINDOW = 60  # seconds

# Discord invite patterns
DISCORD_INVITE_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?'
    r'(?:discord\.gg|discord\.com/invite|discordapp\.com/invite)/'
    r'([a-zA-Z0-9\-]+)',
    re.IGNORECASE
)

# Whitelisted invite codes (your server's invites)
WHITELISTED_INVITE_CODES: Set[str] = {
    "syria",  # discord.gg/syria
}


# =============================================================================
# Caps Spam
# =============================================================================

CAPS_PERCENTAGE = 75
CAPS_MIN_LENGTH = 12


# =============================================================================
# Newline Spam
# =============================================================================

NEWLINE_LIMIT = 20


# =============================================================================
# Character Spam
# =============================================================================

CHAR_REPEAT_LIMIT = 15


# =============================================================================
# Sticker Spam
# =============================================================================

STICKER_SPAM_LIMIT = 3
STICKER_SPAM_TIME_WINDOW = 30  # seconds


# =============================================================================
# Image Duplicate
# =============================================================================

IMAGE_DUPLICATE_LIMIT = 3
IMAGE_DUPLICATE_TIME_WINDOW = 60  # seconds


# =============================================================================
# Attachment Flood
# =============================================================================

ATTACHMENT_LIMIT = 5
ATTACHMENT_TIME_WINDOW = 30  # seconds


# =============================================================================
# Webhook Spam
# =============================================================================

WEBHOOK_MESSAGE_LIMIT = 5
WEBHOOK_TIME_WINDOW = 10  # seconds


# =============================================================================
# Zalgo Detection
# =============================================================================

ZALGO_COMBINING_LIMIT = 10


# =============================================================================
# Memory Bounds
# =============================================================================

MAX_TRACKED_USERS_PER_GUILD = 5000
MAX_IMAGE_HASHES_PER_USER = 50


# =============================================================================
# Arabic Text Handling
# =============================================================================

# Arabic characters range (exempt from char spam and lenient on duplicates)
ARABIC_RANGE = range(0x0600, 0x06FF + 1)

# Arabic tashkeel (diacritical marks) to strip for normalization
ARABIC_TASHKEEL: FrozenSet[str] = frozenset([
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
EXEMPT_ARABIC_GREETINGS: Set[str] = {
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


# =============================================================================
# Scam Detection
# =============================================================================

SCAM_PHRASES: List[str] = [
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

PHISHING_DOMAINS: List[str] = [
    "discord.gift",
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

CRYPTO_WALLET_PATTERN = r'(?:0x[a-fA-F0-9]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})'


# =============================================================================
# Reputation System
# =============================================================================

REPUTATION_NEW = 0
REPUTATION_REGULAR = 50
REPUTATION_TRUSTED = 100
REPUTATION_VETERAN = 200

REP_GAIN_MESSAGE = 0.1
REP_GAIN_DAY_ACTIVE = 1
REP_GAIN_WEEK_NO_VIOLATION = 5

REP_LOSS_WARNING = 10
REP_LOSS_MUTE = 25
REP_LOSS_KICK = 50
REP_LOSS_BAN = 100

REPUTATION_MULTIPLIERS: Dict[int, float] = {
    REPUTATION_NEW: 1.0,
    REPUTATION_REGULAR: 1.25,
    REPUTATION_TRUSTED: 1.5,
    REPUTATION_VETERAN: 2.0,
}


# =============================================================================
# Channel Type Multipliers
# =============================================================================

CHANNEL_TYPE_MULTIPLIERS: Dict[str, float] = {
    "media": 2.0,
    "bot": 0.5,
    "vent": 1.5,
    "meme": 1.5,
    "counting": 0.1,
}


# =============================================================================
# Raid Detection
# =============================================================================

RAID_JOIN_LIMIT = 5
RAID_TIME_WINDOW = 30  # seconds
RAID_SIMILAR_NAME_THRESHOLD = 0.7
RAID_ACCOUNT_AGE_HOURS = 24
RAID_DEFAULT_AVATAR_WEIGHT = 2
RAID_SIMILAR_CREATION_WINDOW = 3600  # 1 hour

NEW_ACCOUNT_DAYS = 7
NEW_MEMBER_ACCOUNT_AGE = 30  # days
NEW_MEMBER_SERVER_AGE = 7  # days
NEW_MEMBER_FLOOD_LIMIT = 5
NEW_MEMBER_DUPLICATE_LIMIT = 2
NEW_MEMBER_MENTION_LIMIT = 3


# =============================================================================
# Auto-Slowmode
# =============================================================================

SLOWMODE_TRIGGER_MESSAGES = 25
SLOWMODE_TIME_WINDOW = 10  # seconds
SLOWMODE_DURATION = 5  # seconds
SLOWMODE_COOLDOWN = 300  # 5 minutes


# =============================================================================
# Cleanup Intervals
# =============================================================================

MESSAGE_HISTORY_CLEANUP = 60  # seconds
VIOLATION_DECAY_TIME = 300  # 5 minutes
REPUTATION_UPDATE_INTERVAL = 3600  # 1 hour


# =============================================================================
# Punishment Durations (Progressive)
# =============================================================================

MUTE_DURATIONS: Dict[int, int] = {
    1: 0,      # First offense: warning only
    2: 300,    # Second offense: 5 minutes
    3: 1800,   # Third offense: 30 minutes
    4: 3600,   # Fourth offense: 1 hour
    5: 86400,  # Fifth+ offense: 24 hours
}


# =============================================================================
# Spam Type Display Names
# =============================================================================

SPAM_DISPLAY_NAMES: Dict[str, str] = {
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
    "sticker_spam": "Sticker Spam",
    "zalgo": "Zalgo/Unicode Abuse",
    "webhook_spam": "Webhook Spam",
}
