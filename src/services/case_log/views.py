"""
Case Log Views
==============

Discord UI views for case log embeds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Optional

import discord

from src.utils.views import (
    CASE_EMOJI,
    MESSAGE_EMOJI,
    DownloadButton,
    InfoButton,
    HistoryButton,
    ExtendButton,
    UnmuteButton,
    ApproveButton,
    EditCaseButton,
)

from .constants import MIN_APPEALABLE_MUTE_SECONDS


class CaseLogView(discord.ui.View):
    """
    View with organized button rows for case log embeds.

    Row 0: Link buttons (Case, Message)
    Row 1: Info buttons (Info, Avatar, History)
    Row 2: Action buttons (Extend, Unmute) - mute embeds only
    Row 3: Approve button (owner only), Appeal button (for eligible cases)
    """

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        message_url: Optional[str] = None,
        case_thread_id: Optional[int] = None,
        is_mute_embed: bool = False,
        case_id: Optional[str] = None,
        action_type: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        show_appeal: bool = False,
    ):
        super().__init__(timeout=None)

        # =================================================================
        # Row 0: Link buttons
        # =================================================================

        if case_thread_id:
            case_url = f"https://discord.com/channels/{guild_id}/{case_thread_id}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
                row=0,
            ))

        if message_url:
            self.add_item(discord.ui.Button(
                label="Message",
                url=message_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
                row=0,
            ))

        # =================================================================
        # Row 1: Info buttons
        # =================================================================

        info_btn = InfoButton(user_id, guild_id)
        info_btn.row = 1
        self.add_item(info_btn)

        avatar_btn = DownloadButton(user_id)
        avatar_btn.row = 1
        self.add_item(avatar_btn)

        history_btn = HistoryButton(user_id, guild_id)
        history_btn.row = 1
        self.add_item(history_btn)

        # =================================================================
        # Row 2: Action buttons (mute embeds only)
        # =================================================================

        if is_mute_embed:
            extend_btn = ExtendButton(user_id, guild_id)
            extend_btn.row = 2
            self.add_item(extend_btn)

            unmute_btn = UnmuteButton(user_id, guild_id)
            unmute_btn.row = 2
            self.add_item(unmute_btn)

        # =================================================================
        # Row 3: Edit button (mods), Approve button (owner only)
        # =================================================================

        if case_id:
            edit_btn = EditCaseButton(case_id)
            edit_btn.row = 3
            self.add_item(edit_btn)

        if case_thread_id and case_id:
            approve_btn = ApproveButton(case_thread_id, case_id)
            approve_btn.row = 3
            self.add_item(approve_btn)

        # NOTE: Appeal button is now sent via DM to the user, not in the case log
        # This allows the affected user to appeal rather than moderators seeing it


class CaseControlPanelView(discord.ui.View):
    """
    Persistent control panel view for case threads.

    This view contains all the buttons for managing a case.
    It's sent once when the case is created and updated in place.

    Row 0: Link buttons (Case, Message)
    Row 1: Info buttons (Info, Avatar, History)
    Row 2: Action buttons (Extend, Unmute) - mute cases only, active status
    Row 3: Edit, Approve buttons
    """

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        case_id: str,
        case_thread_id: int,
        status: str = "open",
        is_mute: bool = False,
        message_url: Optional[str] = None,
    ):
        super().__init__(timeout=None)

        self.user_id = user_id
        self.guild_id = guild_id
        self.case_id = case_id
        self.case_thread_id = case_thread_id
        self.status = status
        self.is_mute = is_mute
        self.message_url = message_url

        self._add_buttons()

    def _add_buttons(self) -> None:
        """Add buttons based on case status and type."""

        # =================================================================
        # Row 0: Link buttons (always present)
        # =================================================================

        if self.case_thread_id:
            case_url = f"https://discord.com/channels/{self.guild_id}/{self.case_thread_id}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
                row=0,
            ))

        if self.message_url:
            self.add_item(discord.ui.Button(
                label="Message",
                url=self.message_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
                row=0,
            ))

        # =================================================================
        # Row 1: Info buttons (always present)
        # =================================================================

        info_btn = InfoButton(self.user_id, self.guild_id)
        info_btn.row = 1
        self.add_item(info_btn)

        avatar_btn = DownloadButton(self.user_id)
        avatar_btn.row = 1
        self.add_item(avatar_btn)

        history_btn = HistoryButton(self.user_id, self.guild_id)
        history_btn.row = 1
        self.add_item(history_btn)

        # =================================================================
        # Row 2: Action buttons (mute cases only, active status)
        # =================================================================

        if self.is_mute and self.status == "open":
            extend_btn = ExtendButton(self.user_id, self.guild_id)
            extend_btn.row = 2
            self.add_item(extend_btn)

            unmute_btn = UnmuteButton(self.user_id, self.guild_id)
            unmute_btn.row = 2
            self.add_item(unmute_btn)

        # =================================================================
        # Row 3: Edit button, Approve button
        # =================================================================

        if self.case_id:
            edit_btn = EditCaseButton(self.case_id)
            edit_btn.row = 3
            self.add_item(edit_btn)

        if self.case_thread_id and self.case_id:
            approve_btn = ApproveButton(self.case_thread_id, self.case_id)
            approve_btn.row = 3
            self.add_item(approve_btn)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "CaseLogView",
    "CaseControlPanelView",
]
