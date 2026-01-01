"""
Ticket System Views
===================

View classes for ticket panel and control panel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord

from src.core.logger import logger

from .buttons import (
    ClaimButton,
    CloseButton,
    AddUserButton,
    ReopenButton,
    TranscriptButton,
    HistoryButton,
    CloseApproveButton,
    CloseDenyButton,
)
from .constants import TICKET_CATEGORIES
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
    - open: Claim, Close, AddUser, History
    - claimed: Close, AddUser, History
    - closed: Reopen, Transcript, History
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
            # Open tickets: Claim, Close, AddUser, History
            self.add_item(ClaimButton(self.ticket_id))
            self.add_item(CloseButton(self.ticket_id))
            self.add_item(AddUserButton(self.ticket_id))
            self.add_item(HistoryButton(self.user_id, self.guild_id))

        elif self.status == "claimed":
            # Claimed tickets: Close, AddUser, History
            self.add_item(CloseButton(self.ticket_id))
            self.add_item(AddUserButton(self.ticket_id))
            self.add_item(HistoryButton(self.user_id, self.guild_id))

        elif self.status == "closed":
            # Closed tickets: Reopen, Transcript, History
            self.add_item(ReopenButton(self.ticket_id))
            self.add_item(TranscriptButton(self.ticket_id))
            self.add_item(HistoryButton(self.user_id, self.guild_id))

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


# =============================================================================
# Priority Selection View
# =============================================================================

class PrioritySelectView(discord.ui.View):
    """View for selecting ticket priority."""

    def __init__(self, ticket_id: str):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id

    @discord.ui.select(
        placeholder="Select priority...",
        options=[
            discord.SelectOption(label="Low", value="low", emoji="⬜"),
            discord.SelectOption(label="Normal", value="normal", emoji="🟦"),
            discord.SelectOption(label="High", value="high", emoji="🟧"),
            discord.SelectOption(label="Urgent", value="urgent", emoji="🟥"),
        ],
    )
    async def priority_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        priority = select.values[0]
        success, message = await bot.ticket_service.set_priority(
            ticket_id=self.ticket_id,
            priority=priority,
            changed_by=interaction.user,
        )

        if success:
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)

        self.stop()
