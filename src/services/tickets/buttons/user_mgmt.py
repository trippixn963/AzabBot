"""
Ticket Buttons - User Management
================================

Buttons for adding and removing users from tickets.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.utils.footer import set_footer
from ..constants import EXTEND_EMOJI, DENY_EMOJI
from .helpers import _is_ticket_staff

if TYPE_CHECKING:
    from src.bot import AzabBot


class AddUserButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_adduser:(?P<ticket_id>T\d+)"):
    """Button to add a user to the ticket thread."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Add User",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_adduser:{ticket_id}",
                emoji=EXTEND_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "AddUserButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        from ..modals import TicketAddUserModal

        logger.tree("Add User Button Clicked", [
            ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ("Ticket ID", self.ticket_id),
        ], emoji="➕")

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
                "You don't have permission to add users to tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TicketAddUserModal(self.ticket_id))


class RemoveUserButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_rmuser:(?P<ticket_id>T\d+):(?P<user_id>\d+)"):
    """Button to remove a user from the ticket thread."""

    def __init__(self, ticket_id: str, user_id: int = 0):
        self.ticket_id = ticket_id
        self.user_id = user_id
        super().__init__(
            discord.ui.Button(
                label="Remove",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_rmuser:{ticket_id}:{user_id}",
                emoji=DENY_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "RemoveUserButton":
        return cls(match.group("ticket_id"), int(match.group("user_id")))

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
                "Only staff can remove users from tickets.",
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
                "Cannot remove users from a closed ticket.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Get the thread and remove the user
        thread = await bot.ticket_service._get_ticket_thread(ticket["thread_id"])
        if not thread:
            await interaction.followup.send("Ticket thread not found.", ephemeral=True)
            return

        # Get the member to remove
        member = interaction.guild.get_member(self.user_id)
        if not member:
            await interaction.followup.send("User not found in server.", ephemeral=True)
            return

        try:
            await thread.remove_user(member)
            logger.tree("User Removed from Ticket", [
                ("Ticket ID", self.ticket_id),
                ("Removed User", f"{member.name} ({member.id})"),
                ("Removed By", f"{interaction.user.name} ({interaction.user.id})"),
            ], emoji="👤")

            # Edit the embed to show user was removed
            try:
                removed_embed = discord.Embed(
                    description=f"👤 ~~{member.mention}~~ was removed from this ticket by {interaction.user.mention}.",
                    color=EmbedColors.GOLD,
                )
                set_footer(removed_embed)
                await interaction.message.edit(embed=removed_embed, view=None)
            except discord.HTTPException:
                pass

        except discord.HTTPException as e:
            logger.error("Failed to remove user from ticket", [
                ("Ticket ID", self.ticket_id),
                ("User ID", str(self.user_id)),
                ("Error", str(e)),
            ])
            await interaction.followup.send(f"Failed to remove user: {e}", ephemeral=True)


class UserAddedView(discord.ui.View):
    """View with remove button for user added notification."""

    def __init__(self, ticket_id: str, user_id: int):
        super().__init__(timeout=None)
        self.add_item(RemoveUserButton(ticket_id, user_id).item)


__all__ = [
    "AddUserButton",
    "RemoveUserButton",
    "UserAddedView",
]
