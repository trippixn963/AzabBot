"""
AzabBot - Server Logs Service Package
=====================================

Comprehensive server activity logging using a forum channel with categorized threads.

Structure:
    - categories.py: LogCategory enum and thread descriptions
    - views.py: Persistent views and buttons for log embeds
    - service.py: Main LoggingService class
    - handlers/: Category-specific handler mixins (planned)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .service import LoggingService
from .categories import LogCategory, THREAD_DESCRIPTIONS
from .views import (
    UserIdButton,
    LogView,
    ReactionLogView,
    MessageLogView,
    ModActionLogView,
    TranscriptLinkView,
    TicketLogView,
    setup_log_views,
)

__all__ = [
    "LoggingService",
    "LogCategory",
    "THREAD_DESCRIPTIONS",
    "UserIdButton",
    "LogView",
    "ReactionLogView",
    "MessageLogView",
    "ModActionLogView",
    "TranscriptLinkView",
    "TicketLogView",
    "setup_log_views",
]
