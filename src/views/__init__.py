"""
Azab Discord Bot - Shared UI Views
===================================

Reusable UI components for moderation commands.

Features:
    - InfoButton: Persistent button showing user details
    - CaseButtonView: View with Case link and Info button
    - And many more...

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

# Import from submodules
from .constants import (
    CASE_EMOJI,
    MESSAGE_EMOJI,
    INFO_EMOJI,
    DOWNLOAD_EMOJI,
    HISTORY_EMOJI,
    EXTEND_EMOJI,
    UNMUTE_EMOJI,
    NOTE_EMOJI,
    APPEAL_EMOJI,
    DENY_EMOJI,
    APPROVE_EMOJI,
)

from .info import (
    InfoButton,
    DownloadButton,
)

from .avatar import (
    OldAvatarButton,
    NewAvatarButton,
)

from .history import (
    build_history_embed,
    build_history_view,
    HistoryButton,
    PaginationPrevButton,
    PaginationNextButton,
    HistoryPaginationView,
)

from .mute_actions import (
    ExtendModal,
    ExtendButton,
    UnmuteModal,
    UnmuteButton,
)

from .case import (
    CaseButtonView,
    MessageButtonView,
    EditCaseModal,
    EditCaseButton,
)

from .select import (
    UserInfoSelect,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# View Registration
# =============================================================================

def setup_moderation_views(bot: "AzabBot") -> None:
    """
    Register persistent views for moderation buttons.

    Call this on bot startup to enable button persistence after restart.
    """
    bot.add_dynamic_items(
        InfoButton,
        DownloadButton,
        OldAvatarButton,
        NewAvatarButton,
        HistoryButton,
        PaginationPrevButton,
        PaginationNextButton,
        ExtendButton,
        UnmuteButton,
        EditCaseButton,
        UserInfoSelect,
    )


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Constants
    "CASE_EMOJI",
    "MESSAGE_EMOJI",
    "INFO_EMOJI",
    "DOWNLOAD_EMOJI",
    "HISTORY_EMOJI",
    "EXTEND_EMOJI",
    "UNMUTE_EMOJI",
    "NOTE_EMOJI",
    "APPEAL_EMOJI",
    "DENY_EMOJI",
    "APPROVE_EMOJI",
    # Info buttons
    "InfoButton",
    "DownloadButton",
    # Avatar buttons
    "OldAvatarButton",
    "NewAvatarButton",
    # History
    "build_history_embed",
    "build_history_view",
    "HistoryButton",
    "PaginationPrevButton",
    "PaginationNextButton",
    "HistoryPaginationView",
    # Mute actions
    "ExtendModal",
    "ExtendButton",
    "UnmuteModal",
    "UnmuteButton",
    # Case views
    "CaseButtonView",
    "MessageButtonView",
    "EditCaseModal",
    "EditCaseButton",
    # Select
    "UserInfoSelect",
    # Setup function
    "setup_moderation_views",
]
