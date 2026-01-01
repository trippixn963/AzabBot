"""
Ticket System Constants
=======================

Categories, colors, timeouts, and configuration for the ticket system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord

from src.core.config import EmbedColors
from src.core.constants import (
    EMOJI_ID_TICKET,
    EMOJI_ID_APPEAL,
    EMOJI_ID_SUGGESTION,
    EMOJI_ID_STAFF,
    EMOJI_ID_TRANSCRIPT,
    EMOJI_ID_APPROVE,
    EMOJI_ID_DENY,
    EMOJI_ID_LOCK,
    EMOJI_ID_UNLOCK,
    EMOJI_ID_EXTEND,
    EMOJI_ID_HISTORY,
    EMOJI_ID_INFO,
    EMOJI_ID_TRANSFER,
    TICKET_CREATION_COOLDOWN,
    AUTO_CLOSE_CHECK_INTERVAL,
    THREAD_DELETE_DELAY,
    CLOSE_REQUEST_COOLDOWN,
)


# =============================================================================
# Emojis
# =============================================================================

TICKET_EMOJI = discord.PartialEmoji(name="ticket", id=EMOJI_ID_TICKET)
PARTNERSHIP_EMOJI = discord.PartialEmoji(name="appeal", id=EMOJI_ID_APPEAL)
SUGGESTION_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon22", id=EMOJI_ID_SUGGESTION)
STAFF_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon23", id=EMOJI_ID_STAFF)
TRANSCRIPT_EMOJI = discord.PartialEmoji(name="transcript", id=EMOJI_ID_TRANSCRIPT)
APPROVE_EMOJI = discord.PartialEmoji(name="approve", id=EMOJI_ID_APPROVE)
DENY_EMOJI = discord.PartialEmoji(name="deny", id=EMOJI_ID_DENY)
LOCK_EMOJI = discord.PartialEmoji(name="lock", id=EMOJI_ID_LOCK)
UNLOCK_EMOJI = discord.PartialEmoji(name="unlock", id=EMOJI_ID_UNLOCK)
EXTEND_EMOJI = discord.PartialEmoji(name="extend", id=EMOJI_ID_EXTEND)
HISTORY_EMOJI = discord.PartialEmoji(name="history", id=EMOJI_ID_HISTORY)
INFO_EMOJI = discord.PartialEmoji(name="info", id=EMOJI_ID_INFO)
TRANSFER_EMOJI = discord.PartialEmoji(name="transfer", id=EMOJI_ID_TRANSFER)


# =============================================================================
# Categories
# =============================================================================

TICKET_CATEGORIES = {
    "support": {
        "label": "Support",
        "emoji": TICKET_EMOJI,
        "description": "General support requests",
        "color": EmbedColors.GREEN,
    },
    "partnership": {
        "label": "Partnership",
        "emoji": PARTNERSHIP_EMOJI,
        "description": "Partnership inquiries",
        "color": EmbedColors.GREEN,
    },
    "suggestion": {
        "label": "Suggestion",
        "emoji": SUGGESTION_EMOJI,
        "description": "Server suggestions",
        "color": EmbedColors.GOLD,
    },
}


# =============================================================================
# Status
# =============================================================================

STATUS_EMOJI = {
    "open": "🟢",
    "claimed": "🔵",
    "closed": "🔴",
}

STATUS_COLOR = {
    "open": EmbedColors.GREEN,
    "claimed": EmbedColors.GOLD,
    "closed": EmbedColors.GOLD,
}


# =============================================================================
# Limits & Timeouts
# =============================================================================

MAX_OPEN_TICKETS_PER_USER = 1
INACTIVE_WARNING_DAYS = 3      # Warn after 3 days of inactivity
INACTIVE_CLOSE_DAYS = 5        # Close after 5 days of inactivity
DELETE_AFTER_CLOSE_DAYS = 7    # Delete thread 7 days after closing
MAX_TRANSCRIPT_MESSAGES = 500  # Max messages to include in transcript


# =============================================================================
# Re-exports from core constants
# =============================================================================

__all__ = [
    # Emojis
    "TICKET_EMOJI",
    "PARTNERSHIP_EMOJI",
    "SUGGESTION_EMOJI",
    "STAFF_EMOJI",
    "TRANSCRIPT_EMOJI",
    "APPROVE_EMOJI",
    "DENY_EMOJI",
    "LOCK_EMOJI",
    "UNLOCK_EMOJI",
    "EXTEND_EMOJI",
    "HISTORY_EMOJI",
    "INFO_EMOJI",
    "TRANSFER_EMOJI",
    # Categories
    "TICKET_CATEGORIES",
    # Status
    "STATUS_EMOJI",
    "STATUS_COLOR",
    # Limits
    "MAX_OPEN_TICKETS_PER_USER",
    "INACTIVE_WARNING_DAYS",
    "INACTIVE_CLOSE_DAYS",
    "DELETE_AFTER_CLOSE_DAYS",
    "MAX_TRANSCRIPT_MESSAGES",
    # Timeouts (from core)
    "TICKET_CREATION_COOLDOWN",
    "AUTO_CLOSE_CHECK_INTERVAL",
    "THREAD_DELETE_DELAY",
    "CLOSE_REQUEST_COOLDOWN",
]
