"""
Ticket System
=============

Modular ticket system for AzabBot.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from .service import TicketService
from .views import (
    TicketPanelView,
    TicketControlPanelView,
    CloseRequestView,
    PrioritySelectView,
    TicketPanelButton,
)
from .buttons import setup_ticket_buttons
from .modals import TicketCreateModal, TicketCloseModal, TicketAddUserModal
from .embeds import (
    build_control_panel_embed,
    build_welcome_embed,
    build_panel_embed,
)
from .constants import TICKET_CATEGORIES, PRIORITY_CONFIG
from .transcript import generate_html_transcript, collect_transcript_messages

if TYPE_CHECKING:
    from src.bot import AzabBot


def setup_ticket_views(bot: "AzabBot") -> None:
    """Register all ticket views and dynamic buttons."""
    # Register persistent views
    bot.add_view(TicketPanelView())

    # Register dynamic items (buttons that persist across restarts)
    bot.add_dynamic_items(TicketPanelButton)
    setup_ticket_buttons(bot)


__all__ = [
    # Service
    "TicketService",
    # Setup
    "setup_ticket_views",
    # Views
    "TicketPanelView",
    "TicketControlPanelView",
    "CloseRequestView",
    "PrioritySelectView",
    "TicketPanelButton",
    # Buttons
    "setup_ticket_buttons",
    # Modals
    "TicketCreateModal",
    "TicketCloseModal",
    "TicketAddUserModal",
    # Embeds
    "build_control_panel_embed",
    "build_welcome_embed",
    "build_panel_embed",
    # Constants
    "TICKET_CATEGORIES",
    "PRIORITY_CONFIG",
    # Transcript
    "generate_html_transcript",
    "collect_transcript_messages",
]
