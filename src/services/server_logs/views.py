"""
Azab Discord Bot - Server Logs Views
=====================================

Persistent views and buttons for server log embeds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional
import re

import discord

from src.core.database import get_db
from src.core.constants import (
    EMOJI_ID_TRANSCRIPT,
    EMOJI_ID_TICKET,
    EMOJI_ID_MESSAGE,
    EMOJI_USERID,
)
from src.views import DownloadButton, OldAvatarButton, NewAvatarButton, CASE_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


# Alias for backward compatibility
USERID_EMOJI = EMOJI_USERID

# Custom emojis for log buttons (using constants for IDs)
TRANSCRIPT_EMOJI = discord.PartialEmoji(name="transcript", id=EMOJI_ID_TRANSCRIPT)
TICKET_EMOJI = discord.PartialEmoji(name="ticket", id=EMOJI_ID_TICKET)
MESSAGE_EMOJI = discord.PartialEmoji(name="message", id=EMOJI_ID_MESSAGE)


class UserIdButton(discord.ui.DynamicItem[discord.ui.Button], template=r"log_userid:(?P<user_id>\d+)"):
    """Button that shows a user's ID in a copyable format."""

    def __init__(self, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="UserID",
                style=discord.ButtonStyle.secondary,
                emoji=USERID_EMOJI,
                custom_id=f"log_userid:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "UserIdButton":
        """Reconstruct the button from the custom_id regex match."""
        user_id = int(match.group("user_id"))
        return cls(user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Send user ID as plain text (not embed) for mobile copy support."""
        await interaction.response.send_message(
            f"`{self.user_id}`",
            ephemeral=True,
        )


class LogView(discord.ui.View):
    """Persistent view for log embeds with Case, UserID, and Download buttons."""

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=None)

        # Check if user has an open case - add Case button first if so
        db = get_db()
        case = db.get_case_log(user_id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))

        self.add_item(UserIdButton(user_id))
        self.add_item(DownloadButton(user_id))


class ReactionLogView(discord.ui.View):
    """View for reaction logs with Jump, UserID, and Avatar buttons."""

    def __init__(self, user_id: int, guild_id: int, message_url: str):
        super().__init__(timeout=None)

        # Jump to message button first
        self.add_item(discord.ui.Button(
            label="Message",
            url=message_url,
            style=discord.ButtonStyle.link,
            emoji=MESSAGE_EMOJI,
        ))

        # Check if user has an open case
        db = get_db()
        case = db.get_case_log(user_id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))

        self.add_item(UserIdButton(user_id))
        self.add_item(DownloadButton(user_id))


class MessageLogView(discord.ui.View):
    """View for message logs with optional Jump, UserID, and Avatar buttons."""

    def __init__(self, user_id: int, guild_id: int, message_url: Optional[str] = None):
        super().__init__(timeout=None)

        # Jump to message button first (if URL provided - for edits, not deletes)
        if message_url:
            self.add_item(discord.ui.Button(
                label="Message",
                url=message_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
            ))

        # Check if user has an open case
        db = get_db()
        case = db.get_case_log(user_id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))

        self.add_item(UserIdButton(user_id))
        self.add_item(DownloadButton(user_id))


class ModActionLogView(discord.ui.View):
    """View for mod action logs with Case button support."""

    def __init__(self, user_id: int, guild_id: int, case_id: Optional[str] = None):
        super().__init__(timeout=None)

        db = get_db()

        # Add Case button if case_id provided - look up thread_id
        if case_id:
            case = db.get_case(case_id)
            if case and case.get("thread_id"):
                case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
                self.add_item(discord.ui.Button(
                    label="Case",
                    url=case_url,
                    style=discord.ButtonStyle.link,
                    emoji=CASE_EMOJI,
                ))

        self.add_item(UserIdButton(user_id))
        self.add_item(DownloadButton(user_id))


class TranscriptLinkView(discord.ui.View):
    """View with a link button to open transcript in browser."""

    def __init__(self, transcript_url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Transcript",
            url=transcript_url,
            style=discord.ButtonStyle.link,
            emoji=TRANSCRIPT_EMOJI,
        ))


class TicketLogView(discord.ui.View):
    """View with Open Ticket button for ticket logs."""

    def __init__(self, guild_id: int, thread_id: int):
        super().__init__(timeout=None)
        ticket_url = f"https://discord.com/channels/{guild_id}/{thread_id}"
        self.add_item(discord.ui.Button(
            label="Open Ticket",
            url=ticket_url,
            style=discord.ButtonStyle.link,
            emoji=TICKET_EMOJI,
        ))


def setup_log_views(bot: "AzabBot") -> None:
    """Register persistent views for log buttons. Call this on bot startup."""
    # Add dynamic views for log buttons
    bot.add_dynamic_items(UserIdButton)
    bot.add_dynamic_items(OldAvatarButton)
    bot.add_dynamic_items(NewAvatarButton)


__all__ = [
    "UserIdButton",
    "LogView",
    "ReactionLogView",
    "MessageLogView",
    "ModActionLogView",
    "TranscriptLinkView",
    "TicketLogView",
    "setup_log_views",
    "USERID_EMOJI",
    "TRANSCRIPT_EMOJI",
    "TICKET_EMOJI",
    "MESSAGE_EMOJI",
]
