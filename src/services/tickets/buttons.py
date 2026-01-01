"""
Ticket System Buttons
=====================

Dynamic button items for the ticket control panel.
All buttons use custom_id prefixes for persistence across restarts.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger
from .constants import (
    APPROVE_EMOJI,
    DENY_EMOJI,
    LOCK_EMOJI,
    UNLOCK_EMOJI,
    TRANSCRIPT_EMOJI,
    EXTEND_EMOJI,
    HISTORY_EMOJI,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Base Dynamic Item Pattern
# =============================================================================

# Custom ID patterns for persistence
CLAIM_PATTERN = re.compile(r"^ticket:claim:(?P<ticket_id>\w+)$")
CLOSE_PATTERN = re.compile(r"^ticket:close:(?P<ticket_id>\w+)$")
ADD_USER_PATTERN = re.compile(r"^ticket:adduser:(?P<ticket_id>\w+)$")
REOPEN_PATTERN = re.compile(r"^ticket:reopen:(?P<ticket_id>\w+)$")
TRANSCRIPT_PATTERN = re.compile(r"^ticket:transcript:(?P<ticket_id>\w+)$")
PRIORITY_PATTERN = re.compile(r"^ticket:priority:(?P<ticket_id>\w+):(?P<priority>\w+)$")
HISTORY_PATTERN = re.compile(r"^ticket:history:(?P<user_id>\d+):(?P<guild_id>\d+)$")
CLOSE_APPROVE_PATTERN = re.compile(r"^ticket:closeapprove:(?P<ticket_id>\w+)$")
CLOSE_DENY_PATTERN = re.compile(r"^ticket:closedeny:(?P<ticket_id>\w+)$")


# =============================================================================
# Claim Button
# =============================================================================

class ClaimButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:claim:(?P<ticket_id>\w+)"):
    """Button to claim a ticket. Only shown when status is 'open'."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Claim",
                style=discord.ButtonStyle.primary,
                custom_id=f"ticket:claim:{ticket_id}",
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
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ You don't have permission to claim tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        success, message = await bot.ticket_service.claim_ticket(
            ticket_id=self.ticket_id,
            staff=interaction.user,
        )

        if success:
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


# =============================================================================
# Close Button
# =============================================================================

class CloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:close:(?P<ticket_id>\w+)"):
    """Button to close a ticket. Opens modal for reason."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Close",
                style=discord.ButtonStyle.danger,
                custom_id=f"ticket:close:{ticket_id}",
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
        from .modals import TicketCloseModal

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
                "❌ Ticket not found.",
                ephemeral=True,
            )
            return

        is_staff = interaction.user.guild_permissions.manage_messages
        is_ticket_owner = ticket["user_id"] == interaction.user.id

        if is_staff:
            # Staff can close directly with modal
            await interaction.response.send_modal(TicketCloseModal(self.ticket_id))
        elif is_ticket_owner:
            # User requests close, needs staff approval
            await interaction.response.defer(ephemeral=True)
            success, message = await bot.ticket_service.request_close(
                ticket_id=self.ticket_id,
                requester=interaction.user,
            )
            if success:
                await interaction.followup.send(f"✅ {message}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Only the ticket owner or staff can close this ticket.",
                ephemeral=True,
            )


# =============================================================================
# Add User Button
# =============================================================================

class AddUserButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:adduser:(?P<ticket_id>\w+)"):
    """Button to add a user to the ticket thread."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Add User",
                style=discord.ButtonStyle.secondary,
                custom_id=f"ticket:adduser:{ticket_id}",
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
        from .modals import TicketAddUserModal

        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ You don't have permission to add users to tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TicketAddUserModal(self.ticket_id))


# =============================================================================
# Reopen Button
# =============================================================================

class ReopenButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:reopen:(?P<ticket_id>\w+)"):
    """Button to reopen a closed ticket."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Reopen",
                style=discord.ButtonStyle.success,
                custom_id=f"ticket:reopen:{ticket_id}",
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

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ Only staff can reopen tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        success, message = await bot.ticket_service.reopen_ticket(
            ticket_id=self.ticket_id,
            reopened_by=interaction.user,
        )

        if success:
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


# =============================================================================
# Transcript Button
# =============================================================================

class TranscriptButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:transcript:(?P<ticket_id>\w+)"):
    """Button to generate/view ticket transcript."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Transcript",
                style=discord.ButtonStyle.secondary,
                custom_id=f"ticket:transcript:{ticket_id}",
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
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ Only staff can view transcripts.",
                ephemeral=True,
            )
            return

        # Check if transcript exists
        transcript = bot.ticket_service.db.get_ticket_transcript(self.ticket_id)
        if not transcript:
            await interaction.response.send_message(
                "❌ No transcript found for this ticket.",
                ephemeral=True,
            )
            return

        # Send link button to open transcript in browser (works on mobile)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Open Transcript",
            style=discord.ButtonStyle.link,
            url=f"https://trippixn.com/api/azab/transcripts/{self.ticket_id}",
            emoji=TRANSCRIPT_EMOJI,
        ))

        await interaction.response.send_message(
            f"📜 Transcript for ticket `#{self.ticket_id}` is ready:",
            view=view,
            ephemeral=True,
        )


# =============================================================================
# Priority Button
# =============================================================================

class PriorityButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:priority:(?P<ticket_id>\w+):(?P<priority>\w+)"):
    """Button to change ticket priority."""

    def __init__(self, ticket_id: str, priority: str, label: str, emoji: str):
        self.ticket_id = ticket_id
        self.priority = priority
        super().__init__(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"ticket:priority:{ticket_id}:{priority}",
                emoji=emoji,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "PriorityButton":
        from .constants import PRIORITY_CONFIG
        priority = match.group("priority")
        info = PRIORITY_CONFIG.get(priority, PRIORITY_CONFIG["normal"])
        return cls(
            match.group("ticket_id"),
            priority,
            priority.title(),
            info["emoji"],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ Only staff can change ticket priority.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        success, message = await bot.ticket_service.set_priority(
            ticket_id=self.ticket_id,
            priority=self.priority,
            changed_by=interaction.user,
        )

        if success:
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


# =============================================================================
# History Button
# =============================================================================

class HistoryButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:history:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """Button to view user's ticket history."""

    def __init__(self, user_id: int, guild_id: int):
        self.user_id = user_id
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="History",
                style=discord.ButtonStyle.secondary,
                custom_id=f"ticket:history:{user_id}:{guild_id}",
                emoji=HISTORY_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "HistoryButton":
        return cls(int(match.group("user_id")), int(match.group("guild_id")))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ Only staff can view ticket history.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        history = bot.ticket_service.db.get_user_tickets(self.user_id, limit=10)

        if not history:
            await interaction.followup.send(
                "📋 No ticket history found for this user.",
                ephemeral=True,
            )
            return

        # Build history embed
        from src.core.config import EmbedColors
        from src.utils.footer import set_footer

        embed = discord.Embed(
            title="📋 Ticket History",
            description=f"Recent tickets for <@{self.user_id}>:",
            color=EmbedColors.BLUE,
        )

        for ticket in history[:10]:
            status_emoji = {"open": "🟢", "claimed": "🔵", "closed": "🔴"}.get(
                ticket["status"], "⚪"
            )
            created = f"<t:{int(ticket['created_at'])}:R>" if ticket.get("created_at") else "Unknown"
            embed.add_field(
                name=f"{status_emoji} #{ticket['ticket_id']} - {ticket['category'].title()}",
                value=f"Subject: {ticket.get('subject', 'N/A')[:50]}\nCreated: {created}",
                inline=False,
            )

        set_footer(embed)
        await interaction.followup.send(embed=embed, ephemeral=True)


# =============================================================================
# Close Request Buttons
# =============================================================================

class CloseApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:closeapprove:(?P<ticket_id>\w+)"):
    """Button for staff to approve a close request."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.success,
                custom_id=f"ticket:closeapprove:{ticket_id}",
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
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ Only staff can approve close requests.",
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
            # Edit the close request message to show it was approved
            try:
                await interaction.message.edit(
                    content=f"✅ Close request approved by {interaction.user.mention}",
                    embed=None,
                    view=None,
                )
            except Exception:
                pass
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


class CloseDenyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:closedeny:(?P<ticket_id>\w+)"):
    """Button for staff to deny a close request."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Deny",
                style=discord.ButtonStyle.danger,
                custom_id=f"ticket:closedeny:{ticket_id}",
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
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "❌ Only staff can deny close requests.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Clear close request status
        bot.ticket_service.db.clear_close_request(self.ticket_id)

        # Edit the close request message to show it was denied
        try:
            await interaction.message.edit(
                content=f"❌ Close request denied by {interaction.user.mention}",
                embed=None,
                view=None,
            )
        except Exception:
            pass

        await interaction.followup.send("Close request denied.", ephemeral=True)


# =============================================================================
# Setup function to register dynamic items
# =============================================================================

def setup_ticket_buttons(bot: commands.Bot) -> None:
    """Register all ticket dynamic buttons with the bot."""
    bot.add_dynamic_items(
        ClaimButton,
        CloseButton,
        AddUserButton,
        ReopenButton,
        TranscriptButton,
        PriorityButton,
        HistoryButton,
        CloseApproveButton,
        CloseDenyButton,
    )
    logger.tree("Ticket Buttons Registered", [
        ("Buttons", "ClaimButton, CloseButton, AddUserButton, ReopenButton, TranscriptButton, PriorityButton, HistoryButton, CloseApproveButton, CloseDenyButton"),
    ], emoji="🎫")
