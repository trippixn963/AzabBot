"""
Ticket System Buttons
=====================

Dynamic button items for the ticket control panel.
All buttons use custom_id prefixes for persistence across restarts.

NOTE: custom_id patterns MUST match the old ticket_service.py patterns
for backward compatibility with existing tickets.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from discord.ext import commands

from src.core.logger import logger

# Import from submodules
from .helpers import _is_ticket_staff, _get_ticket_staff_ids, REVERT_EMOJI
from .claim import ClaimButton
from .close import CloseButton, CloseApproveButton, CloseDenyButton
from .user_mgmt import AddUserButton, RemoveUserButton, UserAddedView
from .transfer import (
    RevertTransferButton,
    TransferNotificationView,
    TransferButton,
    TransferSelectView,
)
from .info import InfoButton, InfoSelectView
from .other import ReopenButton, TranscriptButton


def setup_ticket_buttons(bot: commands.Bot) -> None:
    """Register all ticket dynamic buttons with the bot."""
    bot.add_dynamic_items(
        ClaimButton,
        CloseButton,
        AddUserButton,
        RemoveUserButton,
        RevertTransferButton,
        ReopenButton,
        TranscriptButton,
        InfoButton,
        TransferButton,
        CloseApproveButton,
        CloseDenyButton,
    )
    logger.tree("Ticket Buttons Registered", [
        ("Buttons", "Claim, Close, AddUser, RemoveUser, RevertTransfer, Reopen, Transcript, Info, Transfer, CloseApprove, CloseDeny"),
    ], emoji="🎫")


__all__ = [
    # Helpers
    "_is_ticket_staff",
    "_get_ticket_staff_ids",
    "REVERT_EMOJI",
    # Claim
    "ClaimButton",
    # Close
    "CloseButton",
    "CloseApproveButton",
    "CloseDenyButton",
    # User Management
    "AddUserButton",
    "RemoveUserButton",
    "UserAddedView",
    # Transfer
    "RevertTransferButton",
    "TransferNotificationView",
    "TransferButton",
    "TransferSelectView",
    # Info
    "InfoButton",
    "InfoSelectView",
    # Other
    "ReopenButton",
    "TranscriptButton",
    # Setup
    "setup_ticket_buttons",
]
