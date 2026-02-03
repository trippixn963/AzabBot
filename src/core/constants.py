"""
AzabBot - Centralized Constants
===============================

All magic numbers and constants are defined here for maintainability.
Import from this module instead of hardcoding values.

Author: حَـــــنَّـــــا
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
# NOTE: OthmanBot=8080, AzabBot=8081, JawdatBot=8082, TahaBot=8083
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
CASE_LOG_TIMEOUT = 10.0               # Case logging timeout
GUILD_FETCH_TIMEOUT = 5.0             # Guild/channel fetch timeout
DB_CONNECTION_TIMEOUT = 30.0          # SQLite connection timeout
AUDIT_LOG_WAIT = 0.5                  # Wait for audit log availability
RATE_LIMIT_DELAY = 0.5                # Delay for Discord rate limit protection

# =============================================================================
# Delete After Constants (seconds before auto-delete messages)
# =============================================================================

DELETE_AFTER_SHORT = 5                # Brief warnings, quick confirmations
DELETE_AFTER_MEDIUM = 10              # Standard confirmations, status updates
DELETE_AFTER_LONG = 15                # Alerts, spam warnings
DELETE_AFTER_EXTENDED = 30            # Important notifications, raid alerts

# =============================================================================
# Backoff & Retry Constants
# =============================================================================

BACKOFF_MIN = 30                      # Minimum backoff delay
BACKOFF_MAX = 300                     # Maximum backoff delay (5 minutes)
BACKOFF_MULTIPLIER = 2                # Exponential backoff multiplier
STARTUP_SYNC_BACKOFF_MIN = SECONDS_PER_HOUR  # Startup sync min backoff
STARTUP_SYNC_BACKOFF_MAX = 14400      # Startup sync max backoff (4 hours)
CASE_LOG_BACKOFF_MAX = SECONDS_PER_HOUR  # Case log retry max backoff

# =============================================================================
# Cooldown Constants (in seconds)
# =============================================================================

COMMAND_COOLDOWN = 10                 # General command cooldown
PRISONER_COOLDOWN = 30                # Prisoner response cooldown
TICKET_CREATION_COOLDOWN = 300        # 5 minutes - ticket creation
CLOSE_REQUEST_COOLDOWN = 300          # 5 minutes - close request
APPEAL_COOLDOWN = SECONDS_PER_DAY     # 24 hours - appeal cooldown
PARTNERSHIP_COOLDOWN = 300            # 5 minutes - partnership response cooldown
PRISONER_WARNING_COOLDOWN = 30        # Prisoner warning rate limit

# =============================================================================
# Background Task Intervals (in seconds)
# =============================================================================

QUEUE_PROCESS_INTERVAL = 1            # Queue processing loop interval
PRESENCE_RETRY_DELAY = 5              # Delay between presence update attempts
FORBID_STARTUP_DELAY = 30             # Delay before forbid scan on startup
FORBID_CHECK_INTERVAL = 60            # Forbid expiry check interval
CASE_ARCHIVE_CHECK_INTERVAL = 60      # Case archive check interval
LOG_ARCHIVE_CHECK_INTERVAL = SECONDS_PER_HOUR  # Log archive check interval

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
# Content Moderation Constants
# =============================================================================

# Auto-mute for repeated religion talk violations
RELIGION_OFFENSE_WINDOW = SECONDS_PER_HOUR  # 1 hour window for counting offenses
RELIGION_OFFENSE_THRESHOLD = 3              # Offenses before auto-mute
RELIGION_AUTO_MUTE_MINUTES = 10             # Auto-mute duration in minutes
RELIGION_WARNING_DELETE_AFTER = 3           # Seconds before warning deletes
RELIGION_MUTE_MSG_DELETE_AFTER = 10         # Seconds before mute msg deletes

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
# Prison Constants
# =============================================================================

PRISON_MESSAGE_SCAN_LIMIT = 500       # Messages to scan for context
MESSAGE_HISTORY_SIZE = 10             # Conversation history size
DEFAULT_TIMEOUT_MINUTES = 30          # Default timeout for prisoners
PRISONER_PING_WINDOW = 60             # Window for tracking ping violations
PRISONER_PING_MAX = 3                 # Max pings before timeout

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
# Query & Fetch Limits
# =============================================================================

QUERY_LIMIT_SMALL = 10                # Small queries (history, recent actions)
QUERY_LIMIT_MEDIUM = 50               # Medium queries (leaderboards, lists)
QUERY_LIMIT_LARGE = 100               # Large queries (bulk fetches)
QUERY_LIMIT_XL = 200                  # Extra large queries (forum threads)
QUERY_LIMIT_XXL = 500                 # Maximum queries (full scans)

# =============================================================================
# Text Length Limits
# =============================================================================

MUTE_REASON_MAX_LENGTH = 100          # Max mute reason length
MESSAGE_CONTENT_MAX_LENGTH = 500      # Max message content for logs
LOG_TRUNCATE_SHORT = 50               # Short truncation for logs
LOG_TRUNCATE_MEDIUM = 100             # Medium truncation for logs
LOG_TRUNCATE_LONG = 200               # Long truncation for logs
LOG_TRUNCATE_LENGTH = 50              # Alias for LOG_TRUNCATE_SHORT (backwards compat)
MAX_CONTENT_LENGTH = 1000             # Max content for embeds
MAX_CHANGES_LENGTH = 1000             # Max changes text
THREAD_NAME_MAX_LENGTH = 97           # Discord thread name limit (100 - 3 for "...")

# Discord embed limits
EMBED_DESCRIPTION_LIMIT = 4096
EMBED_FIELD_VALUE_LIMIT = 1024

# =============================================================================
# Modal Field Limits
# =============================================================================

MODAL_FIELD_SHORT = 100               # Short input fields (titles, names)
MODAL_FIELD_MEDIUM = 500              # Medium input fields (reasons, descriptions)
MODAL_FIELD_LONG = 1000               # Long input fields (detailed text)

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

# Service emojis (string format)
EMOJI_USERID = "<:userid:1452512424354643969>"
EMOJI_MODMAIL = "<:modmail:1455197399621750876>"
EMOJI_CLOSE = "<:close:1452963782208032768>"

# =============================================================================
# Discord PartialEmoji IDs
# =============================================================================
# These are numeric IDs for discord.PartialEmoji objects

# UI Button emojis
EMOJI_ID_CASE = 1452426909077213255
EMOJI_ID_MESSAGE = 1452783032460247150
EMOJI_ID_INFO = 1452510787817046197
EMOJI_ID_DOWNLOAD = 1452689360804909148
EMOJI_ID_HISTORY = 1452963786427469894
EMOJI_ID_EXTEND = 1452963975150174410
EMOJI_ID_UNMUTE = 1452964296572272703
EMOJI_ID_NOTE = 1452964649271037974
EMOJI_ID_APPEAL = 1454788569594859726
EMOJI_ID_DENY = 1454788303567065242
EMOJI_ID_APPROVE = 1454788180485345341
EMOJI_ID_LOCK = 1455197454277546055
EMOJI_ID_UNLOCK = 1455200891866190040
EMOJI_ID_TRANSCRIPT = 1455205892319481916
EMOJI_ID_TRANSFER = 1456258089950117888
EMOJI_ID_SAVE = 1455776703468273825
EMOJI_ID_MODMAIL = 1455197399621750876

# Ticket category emojis
EMOJI_ID_TICKET = 1455177168098295983
EMOJI_ID_SUGGESTION = 1455178213771972608
EMOJI_ID_STAFF = 1455178387927732381

# Minutes threshold for duration formatting
MINUTES_PER_DAY = 1440


# =============================================================================
# Moderation Reason Choices (Unified)
# =============================================================================

MODERATION_REASONS = [
    "Spam",
    "Advertising",
    "Harassment",
    "NSFW Content",
    "Trolling",
    "Disrespect",
    "Rule Violation",
    "Bypassing Filters",
    "Excessive Mentions",
    "Off-topic",
    "Impersonation",
    "Scam / Phishing",
    "Raiding",
    "Bot / Selfbot",
    "Evading Punishment",
    "Breaking Discord ToS",
]
"""Reasons for punishment actions: warn, mute, ban, forbid."""

MODERATION_REMOVAL_REASONS = [
    "Appeal Accepted",
    "Time Served",
    "Mistake / Wrong User",
    "Insufficient Evidence",
    "Second Chance",
    "Moderator Request",
    "Resolved with User",
    "Changed Circumstances",
]
"""Reasons for removal actions: unmute, unban, unforbid."""


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
    "CASE_LOG_TIMEOUT",
    "GUILD_FETCH_TIMEOUT",
    "DB_CONNECTION_TIMEOUT",
    "AUDIT_LOG_WAIT",
    "RATE_LIMIT_DELAY",
    # Delete after
    "DELETE_AFTER_SHORT",
    "DELETE_AFTER_MEDIUM",
    "DELETE_AFTER_LONG",
    "DELETE_AFTER_EXTENDED",
    # Backoff & Retry
    "BACKOFF_MIN",
    "BACKOFF_MAX",
    "BACKOFF_MULTIPLIER",
    "STARTUP_SYNC_BACKOFF_MIN",
    "STARTUP_SYNC_BACKOFF_MAX",
    "CASE_LOG_BACKOFF_MAX",
    # Cooldowns
    "COMMAND_COOLDOWN",
    "PRISONER_COOLDOWN",
    "TICKET_CREATION_COOLDOWN",
    "CLOSE_REQUEST_COOLDOWN",
    "APPEAL_COOLDOWN",
    "PARTNERSHIP_COOLDOWN",
    "PRISONER_WARNING_COOLDOWN",
    # Background task intervals
    "QUEUE_PROCESS_INTERVAL",
    "PRESENCE_RETRY_DELAY",
    "FORBID_STARTUP_DELAY",
    "FORBID_CHECK_INTERVAL",
    "CASE_ARCHIVE_CHECK_INTERVAL",
    "LOG_ARCHIVE_CHECK_INTERVAL",
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
    # Content Moderation
    "RELIGION_OFFENSE_WINDOW",
    "RELIGION_OFFENSE_THRESHOLD",
    "RELIGION_AUTO_MUTE_MINUTES",
    "RELIGION_WARNING_DELETE_AFTER",
    "RELIGION_MUTE_MSG_DELETE_AFTER",
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
    # Prison
    "PRISON_MESSAGE_SCAN_LIMIT",
    "MESSAGE_HISTORY_SIZE",
    "DEFAULT_TIMEOUT_MINUTES",
    "PRISONER_PING_WINDOW",
    "PRISONER_PING_MAX",
    # Query limits
    "QUERY_LIMIT_SMALL",
    "QUERY_LIMIT_MEDIUM",
    "QUERY_LIMIT_LARGE",
    "QUERY_LIMIT_XL",
    "QUERY_LIMIT_XXL",
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
    "LOG_TRUNCATE_SHORT",
    "LOG_TRUNCATE_MEDIUM",
    "LOG_TRUNCATE_LONG",
    "LOG_TRUNCATE_LENGTH",
    "MAX_CONTENT_LENGTH",
    "MAX_CHANGES_LENGTH",
    "THREAD_NAME_MAX_LENGTH",
    "EMBED_DESCRIPTION_LIMIT",
    "EMBED_FIELD_VALUE_LIMIT",
    # Modal field limits
    "MODAL_FIELD_SHORT",
    "MODAL_FIELD_MEDIUM",
    "MODAL_FIELD_LONG",
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
    # PartialEmoji IDs
    "EMOJI_ID_CASE",
    "EMOJI_ID_MESSAGE",
    "EMOJI_ID_INFO",
    "EMOJI_ID_DOWNLOAD",
    "EMOJI_ID_HISTORY",
    "EMOJI_ID_EXTEND",
    "EMOJI_ID_UNMUTE",
    "EMOJI_ID_NOTE",
    "EMOJI_ID_APPEAL",
    "EMOJI_ID_DENY",
    "EMOJI_ID_APPROVE",
    "EMOJI_ID_LOCK",
    "EMOJI_ID_UNLOCK",
    "EMOJI_ID_TRANSCRIPT",
    "EMOJI_ID_TRANSFER",
    "EMOJI_ID_SAVE",
    "EMOJI_ID_MODMAIL",
    "EMOJI_ID_TICKET",
    "EMOJI_ID_SUGGESTION",
    "EMOJI_ID_STAFF",
    # Moderation
    "MODERATION_REASONS",
    "MODERATION_REMOVAL_REASONS",
]
