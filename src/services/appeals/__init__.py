"""
AzabBot - Appeals Package
=========================

Ban and mute appeal system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .service import AppealService
from .views import (
    setup_appeal_views,
    AppealActionView,
    AppealApprovedView,
    AppealDeniedView,
    SubmitAppealButton,
)
from .constants import (
    MIN_APPEALABLE_MUTE_DURATION,
    APPEAL_COOLDOWN_SECONDS,
    MAX_APPEALS_PER_WEEK,
    APPEAL_RATE_LIMIT_SECONDS,
)

__all__ = [
    "AppealService",
    "setup_appeal_views",
    "AppealActionView",
    "AppealApprovedView",
    "AppealDeniedView",
    "SubmitAppealButton",
    "MIN_APPEALABLE_MUTE_DURATION",
    "APPEAL_COOLDOWN_SECONDS",
    "MAX_APPEALS_PER_WEEK",
    "APPEAL_RATE_LIMIT_SECONDS",
]
