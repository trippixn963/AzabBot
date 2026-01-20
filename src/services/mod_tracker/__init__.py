"""
Mod Tracker Service Package
===========================

Service for tracking moderator activities in a separate server forum.

Structure:
    - constants.py: Configuration constants
    - helpers.py: Data classes and utility functions
    - logs/: Logging methods mixin package (split for maintainability)
        - base.py: Helper methods
        - member.py: Member activity logging
        - messages.py: Message operation logging
        - moderation.py: Mod action logging
        - channels.py: Channel/thread/role logging
        - voice.py: Voice logging
        - server.py: Server settings/assets logging
        - detection.py: Security alerts and pattern detection
        - misc.py: AutoMod, events, integrations, etc.
    - service.py: Main ModTrackerService class (inherits from logs mixin)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .service import ModTrackerService
from .helpers import CachedMessage, strip_emojis, retry_async
from .constants import (
    MAX_RETRIES,
    BASE_RETRY_DELAY,
    RATE_LIMIT_DELAY,
    INACTIVITY_DAYS,
)

__all__ = [
    "ModTrackerService",
    "CachedMessage",
    "strip_emojis",
    "retry_async",
]
