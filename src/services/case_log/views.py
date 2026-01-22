"""
Case Log Views
==============

Discord UI views for case log embeds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import Optional

import discord

from src.core.database import get_db
from src.core.config import EmbedColors
from src.core.logger import logger
from src.utils.footer import set_footer
from src.utils.views import (
    CASE_EMOJI,
    MESSAGE_EMOJI,
    InfoButton,
    DownloadButton,
    HistoryButton,
    EditCaseButton,
    UserInfoSelect,
)
from src.core.constants import EMOJI_ID_SAVE, EMOJI_ID_TRANSCRIPT

from .constants import MIN_APPEALABLE_MUTE_SECONDS


# =============================================================================
# Evidence Button (shows case evidence in ephemeral message)
# =============================================================================

class EvidenceButton(discord.ui.DynamicItem[discord.ui.Button], template=r"case_evidence:(?P<case_id>[A-Z0-9]+)"):
    """
    Persistent button that shows case evidence when clicked.

    Fetches evidence URLs from database and displays them in an ephemeral message.
    """

    def __init__(self, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Evidence",
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji(name="save", id=EMOJI_ID_SAVE),
                custom_id=f"case_evidence:{case_id}",
            )
        )
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "EvidenceButton":
        case_id = match.group("case_id")
        return cls(case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show evidence in ephemeral message."""
        logger.tree("Evidence Button Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Case ID", self.case_id),
        ], emoji="📷")

        db = get_db()
        evidence_urls = db.get_case_evidence(self.case_id)

        if not evidence_urls:
            await interaction.response.send_message(
                f"📷 **No evidence submitted yet for case `{self.case_id}`**\n\n"
                "Evidence can be submitted by replying to the evidence request message with an image or video.",
                ephemeral=True,
            )
            return

        # Build evidence embed
        embed = discord.Embed(
            title=f"📷 Evidence for Case {self.case_id}",
            color=EmbedColors.INFO,
        )

        # Add evidence links
        evidence_list = []
        for i, url in enumerate(evidence_urls, 1):
            evidence_list.append(f"**{i}.** [View Evidence]({url})")

        embed.description = "\n".join(evidence_list)

        # If only one piece of evidence, show it as an image
        if len(evidence_urls) == 1:
            # Check if it's an image (common extensions)
            url = evidence_urls[0].lower()
            if any(ext in url for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                embed.set_image(url=evidence_urls[0])

        embed.set_footer(text=f"{len(evidence_urls)} piece(s) of evidence")

        await interaction.response.send_message(embed=embed, ephemeral=True)


class CaseLogView(discord.ui.View):
    """
    View with organized button rows for case log embeds.

    Row 0: Link buttons (Case, Message)
    Row 1: Info buttons (Info, Avatar, History)
    Row 2: Edit button (mods)
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
        # Row 2: Edit button (mods)
        # =================================================================

        if case_id:
            edit_btn = EditCaseButton(case_id)
            edit_btn.row = 2
            self.add_item(edit_btn)

        # NOTE: Appeal button is now sent via DM to the user, not in the case log
        # This allows the affected user to appeal rather than moderators seeing it


class CaseControlPanelView(discord.ui.View):
    """
    Persistent control panel view for case threads.

    This view contains all the buttons for managing a case.
    It's sent once when the case is created and updated in place.

    Row 0: User Info dropdown (Info, Avatar, History) + Message link (if available)
    Row 1: Evidence (if exists), Edit buttons
           OR Transcript button (if approved)
    """

    # Transcript emoji (same as tickets, uses constant for ID)
    TRANSCRIPT_EMOJI = discord.PartialEmoji(name="transcript", id=EMOJI_ID_TRANSCRIPT)

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        case_id: str,
        case_thread_id: int,
        status: str = "open",
        is_mute: bool = False,
        message_url: Optional[str] = None,
        has_evidence: bool = False,
        transcript_url: Optional[str] = None,
    ):
        super().__init__(timeout=None)

        self.user_id = user_id
        self.guild_id = guild_id
        self.case_id = case_id
        self.case_thread_id = case_thread_id
        self.status = status
        self.is_mute = is_mute
        self.message_url = message_url
        self.has_evidence = has_evidence
        self.transcript_url = transcript_url

        self._add_components()

    def _add_components(self) -> None:
        """Add components based on case status and type."""

        # =================================================================
        # Row 0: User Info dropdown + Message link (if available)
        # =================================================================

        # User info dropdown (Info, Avatar, History in one menu)
        self.add_item(UserInfoSelect(self.user_id, self.guild_id))

        # Message link button (if we have the original message URL)
        if self.message_url:
            self.add_item(discord.ui.Button(
                label="Message",
                url=self.message_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
                row=0,
            ))

        # =================================================================
        # Row 1: Status-dependent buttons
        # =================================================================

        if self.status == "approved":
            # Approved: Show Transcript button (link to web transcript)
            if self.transcript_url:
                self.add_item(discord.ui.Button(
                    label="Transcript",
                    url=self.transcript_url,
                    style=discord.ButtonStyle.link,
                    emoji=self.TRANSCRIPT_EMOJI,
                    row=1,
                ))

            # Evidence button - still show if evidence was submitted
            if self.has_evidence and self.case_id:
                evidence_btn = EvidenceButton(self.case_id)
                evidence_btn.row = 1
                self.add_item(evidence_btn)
        else:
            # Open/resolved: Show Evidence, Edit buttons
            if self.case_id:
                # Evidence button - only show if evidence was submitted
                if self.has_evidence:
                    evidence_btn = EvidenceButton(self.case_id)
                    evidence_btn.row = 1
                    self.add_item(evidence_btn)

                edit_btn = EditCaseButton(self.case_id)
                edit_btn.row = 1
                self.add_item(edit_btn)


# =============================================================================
# View Registration
# =============================================================================

def setup_case_log_views(bot) -> None:
    """Register persistent views for case log components.

    Note: UserInfoSelect is registered in utils/views.py setup_moderation_views()
    to be shared across case logs, appeals, modmail, and tickets.
    """
    bot.add_dynamic_items(EvidenceButton)
    logger.debug("Case Log Views Registered (EvidenceButton)")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "CaseLogView",
    "CaseControlPanelView",
    "EvidenceButton",
    "UserInfoSelect",
    "setup_case_log_views",
]
