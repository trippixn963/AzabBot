"""
AzabBot - Close Buttons
=======================

Buttons for closing tickets and handling close requests.

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
from ..constants import LOCK_EMOJI, APPROVE_EMOJI, DENY_EMOJI
from .helpers import _is_ticket_staff
from ..modals import TicketCloseModal

if TYPE_CHECKING:
    from src.bot import AzabBot


class CloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_close:(?P<ticket_id>T\d+)"):
    """Button to close a ticket. Opens modal for reason."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Close",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_close:{ticket_id}",
                emoji=LOCK_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "CloseButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("Close Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Ticket ID", self.ticket_id),
        ], emoji="🔒")

        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Get ticket to check permissions
        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message(
                "Ticket not found.",
                ephemeral=True,
            )
            return

        is_staff = _is_ticket_staff(interaction.user)
        is_ticket_owner = ticket["user_id"] == interaction.user.id

        if is_staff:
            # Staff can close directly with modal
            logger.tree("Ticket Close Modal Opened", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ], emoji="🔒")
            await interaction.response.send_modal(TicketCloseModal(self.ticket_id))
        elif is_ticket_owner:
            # User requests close, needs staff approval
            await interaction.response.defer(ephemeral=True)
            success, message = await bot.ticket_service.request_close(
                ticket_id=self.ticket_id,
                requester=interaction.user,
                ticket=ticket,
            )
            if success:
                logger.tree("Close Request Sent", [
                    ("Ticket ID", self.ticket_id),
                    ("Requester", f"{interaction.user.name} ({interaction.user.id})"),
                ], emoji="📝")
                # No ephemeral message - the channel embed with ping is sufficient
            else:
                logger.error("Close Request Failed", [
                    ("Ticket ID", self.ticket_id),
                    ("Requester", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Reason", message),
                ])
                await interaction.followup.send(f"❌ {message}", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Only the ticket owner or staff can close this ticket.",
                ephemeral=True,
            )


class CloseApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_cr_accept:(?P<ticket_id>T\d+):(?P<requester_id>\d+)"):
    """Button for staff to approve a close request."""

    def __init__(self, ticket_id: str, requester_id: int = 0):
        self.ticket_id = ticket_id
        self.requester_id = requester_id
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_cr_accept:{ticket_id}:{requester_id}",
                emoji=APPROVE_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "CloseApproveButton":
        return cls(match.group("ticket_id"), int(match.group("requester_id")))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("Close Approve Button Clicked", [
            ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ("Ticket ID", self.ticket_id),
            ("Requester ID", str(self.requester_id)),
        ], emoji="✅")

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
                "Only staff can approve close requests.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        success, message = await bot.ticket_service.close_ticket(
            ticket_id=self.ticket_id,
            closed_by=interaction.user,
            reason="Close request approved by staff",
        )

        if success:
            logger.tree("Close Request Approved", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
                ("Requester ID", str(self.requester_id)),
            ], emoji="✅")
            # Delete the close request message (close notification embed is sent by close_ticket)
            try:
                await interaction.message.delete()
            except discord.HTTPException as e:
                log_http_error(e, "Delete Close Request Message", [
                    ("Ticket ID", self.ticket_id),
                ])
            # No ephemeral message - the channel close embed is sufficient
        else:
            logger.error("Close Request Approve Failed", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", message),
            ])
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


class CloseDenyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_cr_deny:(?P<ticket_id>T\d+):(?P<requester_id>\d+)"):
    """Button for staff to deny a close request."""

    def __init__(self, ticket_id: str, requester_id: int = 0):
        self.ticket_id = ticket_id
        self.requester_id = requester_id
        super().__init__(
            discord.ui.Button(
                label="Deny",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_cr_deny:{ticket_id}:{requester_id}",
                emoji=DENY_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "CloseDenyButton":
        return cls(match.group("ticket_id"), int(match.group("requester_id")))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("Close Deny Button Clicked", [
            ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ("Ticket ID", self.ticket_id),
            ("Requester ID", str(self.requester_id)),
        ], emoji="❌")

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
                "Only staff can deny close requests.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Clear close request cooldown (use lock for thread safety)
        async with bot.ticket_service._cooldowns_lock:
            bot.ticket_service._close_request_cooldowns.pop(self.ticket_id, None)

        logger.tree("Close Request Denied", [
            ("Ticket ID", self.ticket_id),
            ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ("Requester ID", str(self.requester_id)),
        ], emoji="❌")

        # Get staff stats for the embed
        staff_stats = bot.ticket_service.db.get_staff_ticket_stats(
            interaction.user.id, interaction.guild.id
        )

        # Build deny embed with staff stats
        deny_embed = discord.Embed(
            description=f"❌ Close request denied by {interaction.user.mention}.\n\nThe ticket will remain open.",
            color=EmbedColors.GOLD,
        )
        deny_embed.set_thumbnail(url=interaction.user.display_avatar.url)

        if staff_stats:
            deny_embed.add_field(
                name="Tickets Claimed",
                value=f"`{staff_stats.get('claimed', 0)}`",
                inline=True,
            )
            deny_embed.add_field(
                name="Tickets Closed",
                value=f"`{staff_stats.get('closed', 0)}`",
                inline=True,
            )

        if interaction.user.joined_at:
            deny_embed.add_field(
                name="Staff Since",
                value=f"<t:{int(interaction.user.joined_at.timestamp())}:D>",
                inline=True,
            )

        set_footer(deny_embed)

        # Edit the close request message with the rich embed
        try:
            await interaction.message.edit(
                content=None,
                embed=deny_embed,
                view=None,
            )
        except discord.HTTPException as e:
            log_http_error(e, "Edit Close Request Message", [
                ("Ticket ID", self.ticket_id),
            ])
        # No ephemeral message needed - the embed is visible in the channel


__all__ = [
    "CloseButton",
    "CloseApproveButton",
    "CloseDenyButton",
]
