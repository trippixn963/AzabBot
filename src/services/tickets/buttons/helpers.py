"""
AzabBot - Helper Functions
==========================

Common helper functions for ticket buttons.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord

from src.core.config import get_config
from src.core.constants import EMOJI_ID_UNMUTE


def _is_ticket_staff(user: discord.Member) -> bool:
    """Check if user is ticket staff (configured staff, has manage_messages, OR is developer)."""
    config = get_config()
    # Developer can always access
    if config.developer_id and user.id == config.developer_id:
        return True
    # Check if user is in configured ticket staff
    if config.ticket_support_user_ids and user.id in config.ticket_support_user_ids:
        return True
    if config.ticket_partnership_user_id and user.id == config.ticket_partnership_user_id:
        return True
    if config.ticket_suggestion_user_id and user.id == config.ticket_suggestion_user_id:
        return True
    # Fallback: check for manage_messages permission
    return user.guild_permissions.manage_messages


def _get_ticket_staff_ids(config) -> set:
    """Get all allowed ticket staff user IDs from config."""
    staff_ids = set()
    if config.ticket_support_user_ids:
        staff_ids.update(config.ticket_support_user_ids)
    if config.ticket_partnership_user_id:
        staff_ids.add(config.ticket_partnership_user_id)
    if config.ticket_suggestion_user_id:
        staff_ids.add(config.ticket_suggestion_user_id)
    return staff_ids


# Revert emoji constant
REVERT_EMOJI = discord.PartialEmoji(name="unmute", id=EMOJI_ID_UNMUTE)


__all__ = [
    "_is_ticket_staff",
    "_get_ticket_staff_ids",
    "REVERT_EMOJI",
]
