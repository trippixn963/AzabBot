"""
AzabBot - Transfer
==================

Buttons for transferring tickets between staff members.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.utils.footer import set_footer
from src.utils.discord_rate_limit import log_http_error
from ..constants import TRANSFER_EMOJI
from .helpers import _is_ticket_staff, _get_ticket_staff_ids, REVERT_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


class RevertTransferButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_revert:(?P<ticket_id>T\d+):(?P<original_staff_id>\d+)"):
    """Button to revert a ticket transfer back to the original staff member."""

    def __init__(self, ticket_id: str, original_staff_id: int = 0):
        self.ticket_id = ticket_id
        self.original_staff_id = original_staff_id
        super().__init__(
            discord.ui.Button(
                label="Revert",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_revert:{ticket_id}:{original_staff_id}",
                emoji=REVERT_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "RevertTransferButton":
        return cls(match.group("ticket_id"), int(match.group("original_staff_id")))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions
        if not _is_ticket_staff(interaction.user):
            await interaction.response.send_message(
                "Only staff can revert transfers.",
                ephemeral=True,
            )
            return

        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message(
                "Ticket not found.",
                ephemeral=True,
            )
            return

        if ticket["status"] == "closed":
            await interaction.response.send_message(
                "Cannot revert transfer on a closed ticket.",
                ephemeral=True,
            )
            return

        # Get the original staff member
        original_staff = interaction.guild.get_member(self.original_staff_id)
        if not original_staff:
            await interaction.response.send_message(
                "Original staff member not found in server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Transfer back to original staff
        success, message = await bot.ticket_service.transfer_ticket(
            ticket_id=self.ticket_id,
            new_staff=original_staff,
            transferred_by=interaction.user,
            ticket=ticket,
        )

        if success:
            logger.tree("Transfer Reverted", [
                ("Ticket ID", self.ticket_id),
                ("Reverted To", f"{original_staff.name} ({original_staff.id})"),
                ("Reverted By", f"{interaction.user.name} ({interaction.user.id})"),
            ], emoji="↩️")
            # Edit the message to show transfer was reverted
            try:
                reverted_embed = discord.Embed(
                    description=f"↩️ Transfer reverted to {original_staff.mention} by {interaction.user.mention}.",
                    color=EmbedColors.GOLD,
                )
                set_footer(reverted_embed)
                await interaction.message.edit(content=None, embed=reverted_embed, view=None)
            except discord.HTTPException:
                pass
        else:
            logger.error("Transfer Revert Failed", [
                ("Ticket ID", self.ticket_id),
                ("Original Staff", f"{original_staff.name} ({original_staff.id})"),
                ("Reason", message),
            ])
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


class TransferNotificationView(discord.ui.View):
    """View with revert button for transfer notification."""

    def __init__(self, ticket_id: str, original_staff_id: int):
        super().__init__(timeout=None)
        self.add_item(RevertTransferButton(ticket_id, original_staff_id).item)


class TransferButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_transfer:(?P<ticket_id>T\d+)"):
    """Button to transfer a ticket to another staff member."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Transfer",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_transfer:{ticket_id}",
                emoji=TRANSFER_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "TransferButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("Transfer Button Clicked", [
            ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ("Ticket ID", self.ticket_id),
        ], emoji="🔄")

        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message(
                "Ticket not found.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions (or is developer)
        if not _is_ticket_staff(interaction.user):
            await interaction.response.send_message(
                "You don't have permission to transfer tickets.",
                ephemeral=True,
            )
            return

        if ticket["status"] == "closed":
            await interaction.response.send_message(
                "Cannot transfer a closed ticket.",
                ephemeral=True,
            )
            return

        # Get allowed staff IDs from config
        config = bot.ticket_service.config
        staff_ids = _get_ticket_staff_ids(config)

        # Filter out current claimer
        current_claimer = ticket.get("claimed_by")
        available_staff_ids = [sid for sid in staff_ids if sid != current_claimer]

        if not available_staff_ids:
            await interaction.response.send_message(
                "No other staff members available to transfer to.",
                ephemeral=True,
            )
            return

        # Build options for available staff
        options = []
        for staff_id in available_staff_ids:
            member = interaction.guild.get_member(staff_id)
            if member:
                options.append(discord.SelectOption(
                    label=member.display_name,
                    value=str(staff_id),
                    description=f"@{member.name}",
                ))

        if not options:
            await interaction.response.send_message(
                "No available staff members found in this server.",
                ephemeral=True,
            )
            return

        # Show select for transfer
        view = TransferSelectView(self.ticket_id, options, ticket)
        await interaction.response.send_message(
            "Select a staff member to transfer this ticket to:",
            view=view,
            ephemeral=True,
        )


class TransferSelectView(discord.ui.View):
    """View with select for ticket transfer."""

    def __init__(self, ticket_id: str, options: list, ticket: dict):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.ticket = ticket

        # Add the select with options
        select = discord.ui.Select(
            placeholder="Select staff member...",
            options=options,
            min_values=1,
            max_values=1,
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction) -> None:
        bot: "AzabBot" = interaction.client
        target_id = int(interaction.data["values"][0])

        # Get the member
        target = interaction.guild.get_member(target_id)
        if not target:
            await interaction.response.send_message(
                "Staff member not found in server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Always fetch fresh ticket data (don't use stale self.ticket)
        success, message = await bot.ticket_service.transfer_ticket(
            ticket_id=self.ticket_id,
            new_staff=target,
            transferred_by=interaction.user,
            ticket=None,  # Force fresh fetch
        )

        if success:
            logger.tree("Ticket Transferred", [
                ("Ticket ID", self.ticket_id),
                ("From", f"{interaction.user.name} ({interaction.user.id})"),
                ("To", f"{target.name} ({target.id})"),
            ], emoji="🔄")
            # No ephemeral message - the channel embed is sufficient
            self.stop()
        else:
            logger.error("Ticket Transfer Failed", [
                ("Ticket ID", self.ticket_id),
                ("From", f"{interaction.user.name} ({interaction.user.id})"),
                ("To", f"{target.name} ({target.id})"),
                ("Reason", message),
            ])
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


__all__ = [
    "RevertTransferButton",
    "TransferNotificationView",
    "TransferButton",
    "TransferSelectView",
]
