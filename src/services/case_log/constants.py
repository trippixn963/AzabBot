"""
Case Log Constants
==================

Action types, limits, timeouts, and configuration for the case log system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import timedelta

from src.core.config import EmbedColors


# =============================================================================
# Action Types
# =============================================================================

ACTION_MUTE = "mute"
ACTION_UNMUTE = "unmute"
ACTION_WARN = "warn"
ACTION_BAN = "ban"
ACTION_UNBAN = "unban"
ACTION_TIMEOUT = "timeout"
ACTION_FORBID = "forbid"
ACTION_UNFORBID = "unforbid"
ACTION_EXTENSION = "extension"


# =============================================================================
# Cache Settings
# =============================================================================

THREAD_CACHE_TTL = timedelta(minutes=5)
THREAD_CACHE_MAX_SIZE = 100
FORUM_CACHE_TTL = timedelta(minutes=5)


# =============================================================================
# Profile Update Settings
# =============================================================================

PROFILE_UPDATE_DEBOUNCE = 2.0  # Seconds


# =============================================================================
# Reason Scheduler Settings
# =============================================================================

REASON_CHECK_INTERVAL = 300  # 5 minutes
REASON_EXPIRY_TIME = 3600  # 1 hour
REASON_CLEANUP_AGE = 86400  # 24 hours


# =============================================================================
# Appeal Settings
# =============================================================================

MIN_APPEALABLE_MUTE_SECONDS = 6 * 60 * 60  # 6 hours


# =============================================================================
# Repeat Offender Thresholds
# =============================================================================

REPEAT_MUTE_THRESHOLD = 3
REPEAT_WARN_THRESHOLD = 3


# =============================================================================
# Account Age Warnings
# =============================================================================

NEW_ACCOUNT_WARNING_DAYS = 7
SUSPICIOUS_ACCOUNT_DAYS = 30


# =============================================================================
# Forbid Restriction Emojis
# =============================================================================

FORBID_RESTRICTION_EMOJIS = {
    "reactions": "🚫",
    "attachments": "📎",
    "voice": "🔇",
    "streaming": "📺",
    "embeds": "🔗",
    "threads": "🧵",
    "external_emojis": "😀",
    "stickers": "🎨",
}


# =============================================================================
# Colors (re-export from config for convenience)
# =============================================================================

COLOR_MUTE = EmbedColors.ERROR
COLOR_UNMUTE = EmbedColors.SUCCESS
COLOR_WARN = EmbedColors.WARNING
COLOR_BAN = EmbedColors.ERROR
COLOR_UNBAN = EmbedColors.SUCCESS
COLOR_TIMEOUT = EmbedColors.WARNING
COLOR_FORBID = EmbedColors.WARNING
COLOR_UNFORBID = EmbedColors.SUCCESS
COLOR_EXPIRED = EmbedColors.INFO
COLOR_INFO = EmbedColors.INFO


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Action Types
    "ACTION_MUTE",
    "ACTION_UNMUTE",
    "ACTION_WARN",
    "ACTION_BAN",
    "ACTION_UNBAN",
    "ACTION_TIMEOUT",
    "ACTION_FORBID",
    "ACTION_UNFORBID",
    "ACTION_EXTENSION",
    # Cache Settings
    "THREAD_CACHE_TTL",
    "THREAD_CACHE_MAX_SIZE",
    "FORUM_CACHE_TTL",
    # Profile Update
    "PROFILE_UPDATE_DEBOUNCE",
    # Reason Scheduler
    "REASON_CHECK_INTERVAL",
    "REASON_EXPIRY_TIME",
    "REASON_CLEANUP_AGE",
    # Appeal Settings
    "MIN_APPEALABLE_MUTE_SECONDS",
    # Thresholds
    "REPEAT_MUTE_THRESHOLD",
    "REPEAT_WARN_THRESHOLD",
    "NEW_ACCOUNT_WARNING_DAYS",
    "SUSPICIOUS_ACCOUNT_DAYS",
    # Forbid
    "FORBID_RESTRICTION_EMOJIS",
    # Colors
    "COLOR_MUTE",
    "COLOR_UNMUTE",
    "COLOR_WARN",
    "COLOR_BAN",
    "COLOR_UNBAN",
    "COLOR_TIMEOUT",
    "COLOR_FORBID",
    "COLOR_UNFORBID",
    "COLOR_EXPIRED",
    "COLOR_INFO",
]
