"""
Ticket System Views
===================

View classes for ticket panel and control panel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.config import get_config

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

class TicketPanelView(discord.ui.View):
    """
    View for the ticket creation panel.
    Displays category buttons for creating new tickets.
    """

    def __init__(self):
        super().__init__(timeout=None)

        # Add a button for each category
        for key, info in TICKET_CATEGORIES.items():
            button = discord.ui.Button(
                label=info["label"],
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_cat:{key}",
                emoji=info["emoji"],
            )
            button.callback = self._make_callback(key)
            self.add_item(button)

    def _make_callback(self, category: str):
        """Create a callback for a category button."""
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(TicketCreateModal(category))
        return callback


class TicketPanelButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_cat:(?P<category>\w+)"):
    """Dynamic item for ticket panel category buttons (persistence)."""

    def __init__(self, category: str):
        self.category = category
        info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])
        super().__init__(
            discord.ui.Button(
                label=info["label"],
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_cat:{category}",
                emoji=info["emoji"],
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "TicketPanelButton":
        return cls(match.group("category"))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TicketCreateModal(self.category))


# =============================================================================
# Ticket Control Panel View
# =============================================================================

class TicketControlPanelView(discord.ui.View):
    """
    Main control panel view for a ticket.

    This view is sent once when the ticket is created and
    updated in place as the ticket state changes.

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

        self._add_buttons()

    def _add_buttons(self) -> None:
        """Add buttons based on current ticket status."""
        if self.status == "open":
            # Open tickets: Claim, Close, AddUser, Info
            self.add_item(ClaimButton(self.ticket_id))
            self.add_item(CloseButton(self.ticket_id))
            self.add_item(AddUserButton(self.ticket_id))
            self.add_item(InfoButton(self.ticket_id))

        elif self.status == "claimed":
            # Claimed tickets: Close, Transfer, AddUser, Info
            self.add_item(CloseButton(self.ticket_id))
            self.add_item(TransferButton(self.ticket_id))
            self.add_item(AddUserButton(self.ticket_id))
            self.add_item(InfoButton(self.ticket_id))

        elif self.status == "closed":
            # Closed tickets: Reopen, Transcript (direct link), Info
            self.add_item(ReopenButton(self.ticket_id))
            # Direct link button for transcript (no extra message)
            config = get_config()
            if config.transcript_base_url:
                self.add_item(discord.ui.Button(
                    label="Transcript",
                    style=discord.ButtonStyle.link,
                    url=f"{config.transcript_base_url}/{self.ticket_id}",
                    emoji=TRANSCRIPT_EMOJI,
                ))
            self.add_item(InfoButton(self.ticket_id))

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
