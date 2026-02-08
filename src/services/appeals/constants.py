"""
AzabBot - Appeal Constants
==========================

Constants for the appeal system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Minimum mute duration (in seconds) that can be appealed (1 hour)
MIN_APPEALABLE_MUTE_DURATION = 1 * 60 * 60  # 1 hour in seconds

# Appeal cooldown: 24 hours between appeals for the same case
APPEAL_COOLDOWN_SECONDS = 24 * 60 * 60  # 24 hours

# Appeal rate limit: max 3 appeals per user per week
MAX_APPEALS_PER_WEEK = 3
APPEAL_RATE_LIMIT_SECONDS = 7 * 24 * 60 * 60  # 7 days


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "MIN_APPEALABLE_MUTE_DURATION",
    "APPEAL_COOLDOWN_SECONDS",
    "MAX_APPEALS_PER_WEEK",
    "APPEAL_RATE_LIMIT_SECONDS",
]
