"""
AzabBot - Ticket System Views
=============================

View classes for ticket panel and control panel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.config import get_config
from src.core.logger import logger
from src.views import UserInfoSelect

from .buttons import (
    ClaimButton,
    CloseButton,
    AddUserButton,
    ReopenButton,
    InfoButton,
    TransferButton,
    CloseApproveButton,
    CloseDenyButton,
)
from .constants import TICKET_CATEGORIES, TRANSCRIPT_EMOJI
from .modals import TicketCreateModal

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Ticket Panel View (Category Selection)
# =============================================================================

class TicketCategorySelect(discord.ui.Select):
    """Dropdown select menu for ticket category selection."""

    def __init__(self):
        options = [
            discord.SelectOption(
                label=info["label"],
                value=key,
                description=info["description"],
                emoji=info["emoji"],
            )
            for key, info in TICKET_CATEGORIES.items()
        ]

        super().__init__(
            placeholder="Select a category...",
            options=options,
            custom_id="tkt_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        category = self.values[0]
        logger.tree("Ticket Category Selected", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Category", category),
        ], emoji="🎫")
        await interaction.response.send_modal(TicketCreateModal(category))


class TicketPanelView(discord.ui.View):
    """
    View for the ticket creation panel.
    Displays a dropdown menu for selecting ticket category.
    """

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())


class TicketPanelSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"tkt_select"):
    """Dynamic item for ticket panel select menu (persistence)."""

    def __init__(self):
        options = [
            discord.SelectOption(
                label=info["label"],
                value=key,
                description=info["description"],
                emoji=info["emoji"],
            )
            for key, info in TICKET_CATEGORIES.items()
        ]

        super().__init__(
            discord.ui.Select(
                placeholder="Select a category...",
                options=options,
                custom_id="tkt_select",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match,
    ) -> "TicketPanelSelect":
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        category = self.item.values[0]
        logger.tree("Ticket Category Selected", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Category", category),
        ], emoji="🎫")
        await interaction.response.send_modal(TicketCreateModal(category))


# =============================================================================
# Ticket Control Panel View
# =============================================================================

class TicketControlPanelView(discord.ui.View):
    """
    Main control panel view for a ticket.

    This view is sent once when the ticket is created and
    updated in place as the ticket state changes.

    Layout:
        Row 0: User Info dropdown (Info, Avatar, History for ticket owner)
        Row 1: Action buttons based on status

    Button visibility is based on ticket status:
    - open: Claim, Close, AddUser, Info
    - claimed: Close, Transfer, AddUser, Info
    - closed: Reopen, Transcript, Info
    """

    def __init__(
        self,
        ticket_id: str,
        status: str,
        user_id: int,
        guild_id: int,
    ):
        super().__init__(timeout=None)

        self.ticket_id = ticket_id
        self.status = status
        self.user_id = user_id
        self.guild_id = guild_id

        self._add_components()

    def _add_components(self) -> None:
        """Add components based on current ticket status."""
        # =================================================================
        # Row 0: User Info dropdown (ticket owner's moderation info)
        # =================================================================

        self.add_item(UserInfoSelect(self.user_id, self.guild_id))

        # =================================================================
        # Row 1: Action buttons based on status
        # =================================================================

        if self.status == "open":
            # Open tickets: Claim, Close, AddUser, Info
            claim_btn = ClaimButton(self.ticket_id)
            claim_btn.row = 1
            self.add_item(claim_btn)

            close_btn = CloseButton(self.ticket_id)
            close_btn.row = 1
            self.add_item(close_btn)

            add_user_btn = AddUserButton(self.ticket_id)
            add_user_btn.row = 1
            self.add_item(add_user_btn)

            info_btn = InfoButton(self.ticket_id)
            info_btn.row = 1
            self.add_item(info_btn)

        elif self.status == "claimed":
            # Claimed tickets: Close, Transfer, AddUser, Info
            close_btn = CloseButton(self.ticket_id)
            close_btn.row = 1
            self.add_item(close_btn)

            transfer_btn = TransferButton(self.ticket_id)
            transfer_btn.row = 1
            self.add_item(transfer_btn)

            add_user_btn = AddUserButton(self.ticket_id)
            add_user_btn.row = 1
            self.add_item(add_user_btn)

            info_btn = InfoButton(self.ticket_id)
            info_btn.row = 1
            self.add_item(info_btn)

        elif self.status == "closed":
            # Closed tickets: Reopen, Transcript (direct link), Info
            reopen_btn = ReopenButton(self.ticket_id)
            reopen_btn.row = 1
            self.add_item(reopen_btn)

            # Direct link button for transcript (no extra message)
            config = get_config()
            if config.transcript_base_url:
                self.add_item(discord.ui.Button(
                    label="Transcript",
                    style=discord.ButtonStyle.link,
                    url=f"{config.transcript_base_url}/{self.ticket_id}",
                    emoji=TRANSCRIPT_EMOJI,
                    row=1,
                ))

            info_btn = InfoButton(self.ticket_id)
            info_btn.row = 1
            self.add_item(info_btn)

    @classmethod
    def from_ticket(cls, ticket: dict) -> "TicketControlPanelView":
        """Create view from ticket database record."""
        return cls(
            ticket_id=ticket["ticket_id"],
            status=ticket.get("status", "open"),
            user_id=ticket["user_id"],
            guild_id=ticket.get("guild_id", 0),
        )


# =============================================================================
# Close Request View
# =============================================================================

class CloseRequestView(discord.ui.View):
    """
    View for close request approval.

    When a ticket owner requests to close, this view is shown
    for staff to approve or deny.
    """

    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        self.add_item(CloseApproveButton(ticket_id))
        self.add_item(CloseDenyButton(ticket_id))
