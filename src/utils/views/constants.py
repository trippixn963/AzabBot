"""
Shared UI Constants
===================

Emoji constants used across UI views.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord

from src.core.constants import (
    EMOJI_ID_CASE,
    EMOJI_ID_MESSAGE,
    EMOJI_ID_INFO,
    EMOJI_ID_DOWNLOAD,
    EMOJI_ID_HISTORY,
    EMOJI_ID_EXTEND,
    EMOJI_ID_UNMUTE,
    EMOJI_ID_NOTE,
    EMOJI_ID_APPEAL,
    EMOJI_ID_DENY,
    EMOJI_ID_APPROVE,
)

# App emojis from Discord Developer Portal
CASE_EMOJI = discord.PartialEmoji(name="case", id=EMOJI_ID_CASE)
MESSAGE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon14", id=EMOJI_ID_MESSAGE)
INFO_EMOJI = discord.PartialEmoji(name="info", id=EMOJI_ID_INFO)
DOWNLOAD_EMOJI = discord.PartialEmoji(name="download", id=EMOJI_ID_DOWNLOAD)
HISTORY_EMOJI = discord.PartialEmoji(name="history", id=EMOJI_ID_HISTORY)
EXTEND_EMOJI = discord.PartialEmoji(name="extend", id=EMOJI_ID_EXTEND)
UNMUTE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon3", id=EMOJI_ID_UNMUTE)
NOTE_EMOJI = discord.PartialEmoji(name="note", id=EMOJI_ID_NOTE)
APPEAL_EMOJI = discord.PartialEmoji(name="appeal", id=EMOJI_ID_APPEAL)
DENY_EMOJI = discord.PartialEmoji(name="deny", id=EMOJI_ID_DENY)
APPROVE_EMOJI = discord.PartialEmoji(name="approve", id=EMOJI_ID_APPROVE)


__all__ = [
    "CASE_EMOJI",
    "MESSAGE_EMOJI",
    "INFO_EMOJI",
    "DOWNLOAD_EMOJI",
    "HISTORY_EMOJI",
    "EXTEND_EMOJI",
    "UNMUTE_EMOJI",
    "NOTE_EMOJI",
    "APPEAL_EMOJI",
    "DENY_EMOJI",
    "APPROVE_EMOJI",
]
