"""
AzabBot - Link Constants
========================

Constants for the link command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord

from src.core.constants import EMOJI_ID_APPROVE, EMOJI_ID_DENY


# Custom emojis (black themed)
APPROVE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon18", id=EMOJI_ID_APPROVE)
DENY_EMOJI = discord.PartialEmoji(name="deny", id=EMOJI_ID_DENY)


__all__ = ["APPROVE_EMOJI", "DENY_EMOJI"]
