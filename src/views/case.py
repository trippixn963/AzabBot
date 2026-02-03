"""
AzabBot - Case Button Views
===========================

Buttons for case management (approve, edit, links).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.logger import logger
from src.core.constants import MODAL_FIELD_LONG
from src.utils.footer import set_footer

from .constants import CASE_EMOJI, MESSAGE_EMOJI, NOTE_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Case Button View
# =============================================================================

class CaseButtonView(discord.ui.View):
    """View with Case link button for public response."""

    def __init__(self, guild_id: int, thread_id: int, user_id: int):
        super().__init__(timeout=None)

        # Case link button (links to case thread with control panel)
        url = f"https://discord.com/channels/{guild_id}/{thread_id}"
        self.add_item(discord.ui.Button(
            label="Case",
            url=url,
            style=discord.ButtonStyle.link,
            emoji=CASE_EMOJI,
        ))


# =============================================================================
# Message Button View
# =============================================================================

class MessageButtonView(discord.ui.View):
    """View with a single Message link button."""

    def __init__(self, jump_url: str):
        super().__init__(timeout=None)

        # Message link button
        self.add_item(discord.ui.Button(
            label="Message",
            url=jump_url,
            style=discord.ButtonStyle.link,
            emoji=MESSAGE_EMOJI,
        ))


# =============================================================================
# Edit Case Button & Modal
# =============================================================================

class EditCaseModal(discord.ui.Modal):
    """Modal for editing case reason."""

    def __init__(self, case_id: str, current_reason: Optional[str] = None):
        super().__init__(title="Edit Case Reason")
        self.case_id = case_id

        self.reason_input = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            placeholder="Enter the updated reason for this case...",
            default=current_reason or "",
            required=False,
            max_length=MODAL_FIELD_LONG,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        new_reason = self.reason_input.value.strip() or None

        try:
            # Update case in database
            db = get_db()
            success = db.update_case_reason(self.case_id, new_reason, interaction.user.id)

            if success:
                await interaction.response.send_message(
                    f"✏️ **Case Updated** by {interaction.user.mention}\n"
                    f"**New Reason:** {new_reason or 'No reason provided'}",
                    ephemeral=False,
                )

                logger.tree("Case Edited", [
                    ("Case ID", self.case_id),
                    ("Editor", f"{interaction.user} ({interaction.user.id})"),
                    ("New Reason", (new_reason or "None")[:50]),
                ], emoji="✏️")
            else:
                await interaction.response.send_message(
                    "❌ Failed to update case. Case may not exist.",
                    ephemeral=True,
                )
        except Exception as e:
            logger.error("Edit Case Failed", [
                ("Case ID", self.case_id),
                ("Error", str(e)[:50]),
            ])
            await interaction.response.send_message(
                "❌ An error occurred while updating the case.",
                ephemeral=True,
            )


class EditCaseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"edit_case:(?P<case_id>\w+)"):
    """
    Persistent edit button that allows moderators to edit case reason.

    Works after bot restart by using DynamicItem with regex pattern.
    Only moderators can use this button.
    """

    def __init__(self, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Edit",
                style=discord.ButtonStyle.secondary,
                emoji=NOTE_EMOJI,
                custom_id=f"edit_case:{case_id}",
            )
        )
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "EditCaseButton":
        """Reconstruct the button from the custom_id regex match."""
        case_id = match.group("case_id")
        return cls(case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle edit button click - only moderators can use."""
        logger.tree("Edit Case Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Case ID", self.case_id),
        ], emoji="✏️")

        from src.core.config import get_config, is_owner

        config = get_config()

        # Check if user is moderator or developer
        is_mod = False
        if isinstance(interaction.user, discord.Member):
            if is_owner(interaction.user.id):
                is_mod = True
            elif interaction.user.guild_permissions.moderate_members:
                is_mod = True
            elif config.moderation_role_id and interaction.user.get_role(config.moderation_role_id):
                is_mod = True

        if not is_mod:
            await interaction.response.send_message(
                "❌ Only moderators can edit cases.",
                ephemeral=True,
            )
            return

        try:
            # Get current case info
            db = get_db()
            case = db.get_case(self.case_id)

            current_reason = case.get("reason") if case else None

            # Show edit modal
            modal = EditCaseModal(self.case_id, current_reason)
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error("Edit Case Button Failed", [
                ("Case ID", self.case_id),
                ("Error", str(e)[:50]),
            ])
            await interaction.response.send_message(
                "❌ Failed to open edit modal.",
                ephemeral=True,
            )


__all__ = [
    "CaseButtonView",
    "MessageButtonView",
    "EditCaseModal",
    "EditCaseButton",
]
