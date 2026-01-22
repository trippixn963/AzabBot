"""
AzabBot - Other Buttons
=======================

Reopen and Transcript buttons.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config
from ..constants import UNLOCK_EMOJI, TRANSCRIPT_EMOJI
from .helpers import _is_ticket_staff

if TYPE_CHECKING:
    from src.bot import AzabBot


class ReopenButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_reopen:(?P<ticket_id>T\d+)"):
    """Button to reopen a closed ticket."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Reopen",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_reopen:{ticket_id}",
                emoji=UNLOCK_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "ReopenButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions (or is developer)
        if not _is_ticket_staff(interaction.user):
            await interaction.response.send_message(
                "Only staff can reopen tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        success, message = await bot.ticket_service.reopen_ticket(
            ticket_id=self.ticket_id,
            reopened_by=interaction.user,
        )

        if success:
            logger.tree("Ticket Reopened (Button)", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ], emoji="🔓")
            # No ephemeral message - the channel embed is sufficient
        else:
            logger.error("Ticket Reopen Failed (Button)", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", message),
            ])
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


class TranscriptButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_transcript:(?P<ticket_id>T\d+)"):
    """Button to generate/view ticket transcript."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Transcript",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_transcript:{ticket_id}",
                emoji=TRANSCRIPT_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "TranscriptButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("Transcript Button Clicked", [
            ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ("Ticket ID", self.ticket_id),
        ], emoji="📜")

        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions (or is developer)
        if not _is_ticket_staff(interaction.user):
            await interaction.response.send_message(
                "Only staff can view transcripts.",
                ephemeral=True,
            )
            return

        # Check if transcript exists
        transcript = bot.ticket_service.db.get_ticket_transcript(self.ticket_id)
        if not transcript:
            await interaction.response.send_message(
                "No transcript found for this ticket.",
                ephemeral=True,
            )
            return

        # Send link button to open transcript in browser (works on mobile)
        config = get_config()
        if not config.transcript_base_url:
            await interaction.response.send_message(
                "❌ Transcript viewer is not configured.",
                ephemeral=True,
            )
            return

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Transcript",
            style=discord.ButtonStyle.link,
            url=f"{config.transcript_base_url}/{self.ticket_id}",
            emoji=TRANSCRIPT_EMOJI,
        ))

        await interaction.response.send_message(
            f"📜 Transcript for ticket `#{self.ticket_id}` is ready:",
            view=view,
            ephemeral=True,
        )


__all__ = [
    "ReopenButton",
    "TranscriptButton",
]
