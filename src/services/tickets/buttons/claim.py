"""
AzabBot - Claim Button
======================

Button to claim a ticket.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config
from ..constants import APPROVE_EMOJI
from .helpers import _is_ticket_staff

if TYPE_CHECKING:
    from src.bot import AzabBot


class ClaimButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_claim:(?P<ticket_id>T\d+)"):
    """Button to claim a ticket. Only shown when status is 'open'."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Claim",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_claim:{ticket_id}",
                emoji=APPROVE_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "ClaimButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("Claim Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Ticket ID", self.ticket_id),
        ], emoji="✋")

        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)

        # Check if user has staff permissions (or is developer)
        if not _is_ticket_staff(interaction.user):
            await interaction.response.send_message(
                "You don't have permission to claim tickets.",
                ephemeral=True,
            )
            return

        # Ticket owner can't claim their own ticket (unless they're developer)
        config = get_config()
        is_owner = config.owner_id and interaction.user.id == config.owner_id
        if ticket and interaction.user.id == ticket["user_id"] and not is_owner:
            await interaction.response.send_message(
                "Only staff can claim tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        success, message = await bot.ticket_service.claim_ticket(
            ticket_id=self.ticket_id,
            staff=interaction.user,
            ticket=ticket,
        )

        if success:
            logger.tree("Ticket Claimed (Button)", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ], emoji="✋")
            # No ephemeral message - the channel embed is sufficient
        else:
            logger.error("Ticket Claim Failed (Button)", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", message),
            ])
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


__all__ = ["ClaimButton"]
