"""
AzabBot - Centralized Constants
================================

All magic numbers and constants are defined here for maintainability.
Import from this module instead of hardcoding values.

Author: John Hamwi
Server: discord.gg/syria
"""

# =============================================================================
# Time Constants (in seconds)
# =============================================================================

# Base time units
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
SECONDS_PER_WEEK = 604800

# Milliseconds conversion
MS_PER_SECOND = 1000

# =============================================================================
# Network Constants
# =============================================================================

# Health check server port (AzabBot uses 8081)
# Note: OthmanBot=8080, AzabBot=8081, JawdatBot=8082, TahaBot=8083
HEALTH_CHECK_PORT = 8081

# Stats API port
STATS_API_PORT = 8087

# =============================================================================
# Interval Constants (in seconds)
# =============================================================================

# Background task intervals
MUTE_CHECK_INTERVAL = 30              # Check for expired mutes
PRESENCE_UPDATE_INTERVAL = 60         # Rotate presence status
HOURLY_TASK_INTERVAL = SECONDS_PER_HOUR  # Hourly background tasks
AUTO_CLOSE_CHECK_INTERVAL = SECONDS_PER_HOUR  # Check for auto-close tickets

# Cache TTL
CACHE_TTL = 300                       # 5 minutes - general cache
PRISONER_STATS_TTL = 60               # 1 minute - prisoner stats cache
MESSAGE_CACHE_TTL = SECONDS_PER_HOUR  # 1 hour - message cache

# =============================================================================
# Timeout Constants (in seconds)
# =============================================================================

API_TIMEOUT = 10                      # External API request timeout
SHUTDOWN_TIMEOUT = 10                 # Graceful shutdown timeout
DRAIN_TIMEOUT = 10.0                  # Queue drain timeout

# =============================================================================
# Cooldown Constants (in seconds)
# =============================================================================

COMMAND_COOLDOWN = 10                 # General command cooldown
PRISONER_COOLDOWN = 30                # Prisoner response cooldown
TICKET_CREATION_COOLDOWN = 300        # 5 minutes - ticket creation
CLOSE_REQUEST_COOLDOWN = 300          # 5 minutes - close request
APPEAL_COOLDOWN = SECONDS_PER_DAY     # 24 hours - appeal cooldown

# =============================================================================
# Raid & Security Constants
# =============================================================================

# Raid detection
RAID_THRESHOLD = 10                   # Joins to trigger raid detection
RAID_WINDOW = 30                      # Window in seconds

# Lockdown
AUTO_UNLOCK_DURATION = 300            # 5 minutes - auto unlock
LOCKDOWN_COOLDOWN = 600               # 10 minutes - lockdown cooldown

# Anti-nuke
ANTINUKE_TIME_WINDOW = 60             # 1 minute - action window

# Mod tracker windows
BULK_ACTION_WINDOW = 300              # 5 minutes - bulk action detection
SUSPICIOUS_UNBAN_WINDOW = SECONDS_PER_HOUR  # 1 hour - suspicious unban
BAN_HISTORY_TTL = SECONDS_PER_DAY     # 24 hours - ban history
MASS_PERMISSION_WINDOW = 300          # 5 minutes - mass permission changes
TARGET_HARASSMENT_WINDOW = 300        # 5 minutes - target harassment
TARGET_HARASSMENT_TTL = SECONDS_PER_HOUR  # 1 hour - harassment history

# =============================================================================
# Moderation Constants
# =============================================================================

# Warning decay
WARNING_DECAY_DAYS = 30               # Days before warnings decay

# Snipe settings
SNIPE_MAX_AGE = 600                   # 10 minutes - snipe expiry
SNIPE_LIMIT = 10                      # Max snipes per channel

# Purge settings
MAX_PURGE_AMOUNT = 500                # Max messages to purge
DEFAULT_PURGE_AMOUNT = 100            # Default purge amount
BULK_DELETE_LIMIT = 100               # Discord bulk delete limit

# Thresholds
BULK_DELETE_THRESHOLD = 10            # Deletes to trigger alert
MASS_BAN_THRESHOLD = 5                # Bans to trigger alert
MASS_KICK_THRESHOLD = 5               # Kicks to trigger alert
MASS_ROLE_THRESHOLD = 3               # Role changes to trigger alert
MASS_CHANNEL_THRESHOLD = 3            # Channel changes to trigger alert
TARGET_HARASSMENT_THRESHOLD = 3       # Actions to trigger alert
MEMBERS_REMOVED_ALERT = 50            # Members removed to trigger alert

# =============================================================================
# Ticket Constants
# =============================================================================

THREAD_DELETE_DELAY = SECONDS_PER_HOUR  # 1 hour - delay before deleting thread

# =============================================================================
# AI/Prison Constants
# =============================================================================

RESPONSE_PROBABILITY = 70             # % chance to respond
MAX_RESPONSE_LENGTH = 150             # Max AI response length
PRISON_MESSAGE_SCAN_LIMIT = 500       # Messages to scan for context
MESSAGE_HISTORY_SIZE = 10             # Conversation history size
DEFAULT_TIMEOUT_MINUTES = 30          # Default timeout for prisoners

# =============================================================================
# Cache & Limit Constants
# =============================================================================

# Message caches
LAST_MESSAGES_LIMIT = 5000            # Last messages cache
ATTACHMENT_CACHE_LIMIT = 500          # Attachment cache
MESSAGE_CACHE_LIMIT = 5000            # General message cache
EDITSNIPE_CHANNEL_LIMIT = 500         # Edit snipe channel limit
MUTE_REASONS_LIMIT = 1000             # Mute reasons cache

# Mod tracker
MESSAGE_CACHE_SIZE = 50               # Messages per mod
MESSAGE_CACHE_MAX_MODS = 100          # Max mods to cache

# Queue
QUEUE_MAX_SIZE = 500                  # Max queue size

# Polls
POLLS_CLEANUP_LIMIT = 100             # Polls to check for cleanup

# =============================================================================
# Text Length Limits
# =============================================================================

MUTE_REASON_MAX_LENGTH = 100          # Max mute reason length
MESSAGE_CONTENT_MAX_LENGTH = 500      # Max message content for logs
LOG_TRUNCATE_LENGTH = 50              # Truncate length for logs
MAX_CONTENT_LENGTH = 1000             # Max content for embeds
MAX_CHANGES_LENGTH = 1000             # Max changes text

# Discord embed limits
EMBED_DESCRIPTION_LIMIT = 4096
EMBED_FIELD_VALUE_LIMIT = 1024

# =============================================================================
# Discord Limits
# =============================================================================

MAX_EMBEDS_PER_REQUEST = 10           # Discord webhook limit
MAX_AUTOCOMPLETE_RESULTS = 25         # Discord autocomplete limit

# =============================================================================
# Data Retention Constants
# =============================================================================

LOG_RETENTION_DAYS = 30               # Auto-delete logs older than this
PENDING_REASON_MAX_AGE = SECONDS_PER_HOUR  # 1 hour - pending reason expiry
PENDING_REASON_CLEANUP_AGE = SECONDS_PER_DAY  # 24 hours - cleanup age
VOICE_ACTIVITY_MAX_AGE = SECONDS_PER_DAY  # 24 hours - voice activity
SPAM_DECAY_SECONDS = 300              # 5 minutes - spam violation decay
PROMO_DURATION_MINUTES = 10           # Promo message duration

# =============================================================================
# Stats API Constants
# =============================================================================

STATS_CACHE_TTL = 30                  # Stats cache TTL
RATE_LIMIT_REQUESTS = 60              # Requests per minute
RATE_LIMIT_BURST = 10                 # Burst limit

# Leaderboard limits
TOP_OFFENDERS_LIMIT = 10
MODERATOR_LEADERBOARD_LIMIT = 10
RECENT_ACTIONS_LIMIT = 10
DEFAULT_QUERY_LIMIT = 25

# =============================================================================
# Discord Colors (decimal format)
# =============================================================================

COLOR_GREEN = 0x2ECC71                # Success/positive
COLOR_RED = 0xE74C3C                  # Error/ban
COLOR_ORANGE = 0xE67E22               # Warning/mute
COLOR_BLUE = 0x3498DB                 # Info/neutral
COLOR_GOLD = 0xF1C40F                 # Premium/highlight
COLOR_PURPLE = 0x9B59B6               # Special actions

# =============================================================================
# HTTP Status Codes
# =============================================================================

HTTP_OK = 200
HTTP_RATE_LIMITED = 429
HTTP_SERVER_ERROR = 500

# =============================================================================
# Custom Discord Emojis
# =============================================================================
# Note: These are custom emoji IDs from the Syria server. If emojis are
# deleted or changed, update the IDs here.

# Moderation action emojis (for history command)
EMOJI_MUTE = "<:mute:1337255401531154432>"
EMOJI_BAN = "<:ban:1337255389103284284>"
EMOJI_WARN = "<:warn:1337255414315393065>"
EMOJI_TIMEOUT = "<:timeout:1337255426600611840>"
EMOJI_KICK = "<:kick:1337255404907593759>"

# Service emojis
EMOJI_USERID = "<:userid:1452512424354643969>"
EMOJI_MODMAIL = "<:modmail:1455197399621750876>"
EMOJI_CLOSE = "<:close:1452963782208032768>"

# Minutes threshold for duration formatting
MINUTES_PER_DAY = 1440

# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Time
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "SECONDS_PER_WEEK",
    "MS_PER_SECOND",
    # Network
    "HEALTH_CHECK_PORT",
    "STATS_API_PORT",
    # Intervals
    "MUTE_CHECK_INTERVAL",
    "PRESENCE_UPDATE_INTERVAL",
    "HOURLY_TASK_INTERVAL",
    "AUTO_CLOSE_CHECK_INTERVAL",
    "CACHE_TTL",
    "PRISONER_STATS_TTL",
    "MESSAGE_CACHE_TTL",
    # Timeouts
    "API_TIMEOUT",
    "SHUTDOWN_TIMEOUT",
    "DRAIN_TIMEOUT",
    # Cooldowns
    "COMMAND_COOLDOWN",
    "PRISONER_COOLDOWN",
    "TICKET_CREATION_COOLDOWN",
    "CLOSE_REQUEST_COOLDOWN",
    "APPEAL_COOLDOWN",
    # Raid & Security
    "RAID_THRESHOLD",
    "RAID_WINDOW",
    "AUTO_UNLOCK_DURATION",
    "LOCKDOWN_COOLDOWN",
    "ANTINUKE_TIME_WINDOW",
    "BULK_ACTION_WINDOW",
    "SUSPICIOUS_UNBAN_WINDOW",
    "BAN_HISTORY_TTL",
    "MASS_PERMISSION_WINDOW",
    "TARGET_HARASSMENT_WINDOW",
    "TARGET_HARASSMENT_TTL",
    # Moderation
    "WARNING_DECAY_DAYS",
    "SNIPE_MAX_AGE",
    "SNIPE_LIMIT",
    "MAX_PURGE_AMOUNT",
    "DEFAULT_PURGE_AMOUNT",
    "BULK_DELETE_LIMIT",
    "BULK_DELETE_THRESHOLD",
    "MASS_BAN_THRESHOLD",
    "MASS_KICK_THRESHOLD",
    "MASS_ROLE_THRESHOLD",
    "MASS_CHANNEL_THRESHOLD",
    "TARGET_HARASSMENT_THRESHOLD",
    "MEMBERS_REMOVED_ALERT",
    # Tickets
    "THREAD_DELETE_DELAY",
    # AI/Prison
    "RESPONSE_PROBABILITY",
    "MAX_RESPONSE_LENGTH",
    "PRISON_MESSAGE_SCAN_LIMIT",
    "MESSAGE_HISTORY_SIZE",
    "DEFAULT_TIMEOUT_MINUTES",
    # Caches
    "LAST_MESSAGES_LIMIT",
    "ATTACHMENT_CACHE_LIMIT",
    "MESSAGE_CACHE_LIMIT",
    "EDITSNIPE_CHANNEL_LIMIT",
    "MUTE_REASONS_LIMIT",
    "MESSAGE_CACHE_SIZE",
    "MESSAGE_CACHE_MAX_MODS",
    "QUEUE_MAX_SIZE",
    "POLLS_CLEANUP_LIMIT",
    # Text limits
    "MUTE_REASON_MAX_LENGTH",
    "MESSAGE_CONTENT_MAX_LENGTH",
    "LOG_TRUNCATE_LENGTH",
    "MAX_CONTENT_LENGTH",
    "MAX_CHANGES_LENGTH",
    "EMBED_DESCRIPTION_LIMIT",
    "EMBED_FIELD_VALUE_LIMIT",
    # Discord limits
    "MAX_EMBEDS_PER_REQUEST",
    "MAX_AUTOCOMPLETE_RESULTS",
    # Retention
    "LOG_RETENTION_DAYS",
    "PENDING_REASON_MAX_AGE",
    "PENDING_REASON_CLEANUP_AGE",
    "VOICE_ACTIVITY_MAX_AGE",
    "SPAM_DECAY_SECONDS",
    "PROMO_DURATION_MINUTES",
    # Stats API
    "STATS_CACHE_TTL",
    "RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_BURST",
    "TOP_OFFENDERS_LIMIT",
    "MODERATOR_LEADERBOARD_LIMIT",
    "RECENT_ACTIONS_LIMIT",
    "DEFAULT_QUERY_LIMIT",
    # Colors
    "COLOR_GREEN",
    "COLOR_RED",
    "COLOR_ORANGE",
    "COLOR_BLUE",
    "COLOR_GOLD",
    "COLOR_PURPLE",
    # HTTP
    "HTTP_OK",
    "HTTP_RATE_LIMITED",
    "HTTP_SERVER_ERROR",
    # Emojis
    "EMOJI_MUTE",
    "EMOJI_BAN",
    "EMOJI_WARN",
    "EMOJI_TIMEOUT",
    "EMOJI_KICK",
    "EMOJI_USERID",
    "EMOJI_MODMAIL",
    "EMOJI_CLOSE",
    # Duration
    "MINUTES_PER_DAY",
]
