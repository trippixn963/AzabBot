"""
Case Log Service
================

Modular case log service for AzabBot.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from .service import CaseLogService
from .views import CaseLogView, CaseControlPanelView
from .constants import (
    ACTION_MUTE,
    ACTION_UNMUTE,
    ACTION_WARN,
    ACTION_BAN,
    ACTION_UNBAN,
    ACTION_TIMEOUT,
    ACTION_FORBID,
    ACTION_UNFORBID,
    ACTION_EXTENSION,
    MIN_APPEALABLE_MUTE_SECONDS,
)
from .embeds import (
    build_mute_embed,
    build_timeout_embed,
    build_warn_embed,
    build_unmute_embed,
    build_expired_embed,
    build_ban_embed,
    build_unban_embed,
    build_forbid_embed,
    build_unforbid_embed,
    build_profile_embed,
    build_control_panel_embed,
)
from .utils import (
    has_valid_media_evidence,
    parse_duration_to_seconds,
    format_duration_precise,
    format_age,
)
from .transcript import (
    Transcript,
    TranscriptMessage,
    TranscriptAttachment,
    TranscriptEmbed,
    TranscriptEmbedField,
    TranscriptBuilder,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


def setup_case_views(bot: "AzabBot") -> None:
    """Register case log views if needed."""
    # CaseLogView uses timeout=None so it persists
    # No persistent views needed at startup currently
    pass


__all__ = [
    # Service
    "CaseLogService",
    # Setup
    "setup_case_views",
    # Views
    "CaseLogView",
    "CaseControlPanelView",
    # Constants
    "ACTION_MUTE",
    "ACTION_UNMUTE",
    "ACTION_WARN",
    "ACTION_BAN",
    "ACTION_UNBAN",
    "ACTION_TIMEOUT",
    "ACTION_FORBID",
    "ACTION_UNFORBID",
    "ACTION_EXTENSION",
    "MIN_APPEALABLE_MUTE_SECONDS",
    # Embeds
    "build_mute_embed",
    "build_timeout_embed",
    "build_warn_embed",
    "build_unmute_embed",
    "build_expired_embed",
    "build_ban_embed",
    "build_unban_embed",
    "build_forbid_embed",
    "build_unforbid_embed",
    "build_profile_embed",
    "build_control_panel_embed",
    # Utils
    "has_valid_media_evidence",
    "parse_duration_to_seconds",
    "format_duration_precise",
    "format_age",
    # Transcript
    "Transcript",
    "TranscriptMessage",
    "TranscriptAttachment",
    "TranscriptEmbed",
    "TranscriptEmbedField",
    "TranscriptBuilder",
]
