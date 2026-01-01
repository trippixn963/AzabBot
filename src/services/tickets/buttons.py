"""
Ticket System Buttons
=====================

Dynamic button items for the ticket control panel.
All buttons use custom_id prefixes for persistence across restarts.

NOTE: custom_id patterns MUST match the old ticket_service.py patterns
for backward compatibility with existing tickets.

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
    INFO_EMOJI,
    TRANSFER_EMOJI,
    STATUS_EMOJI,
    TICKET_CATEGORIES,
    PRIORITY_CONFIG,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Claim Button
# =============================================================================

class ClaimButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_claim:(?P<ticket_id>T\d+)"):
    """Button to claim a ticket. Only shown when status is 'open'."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Claim",
                style=discord.ButtonStyle.primary,
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
                "You don't have permission to claim tickets.",
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

class CloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_close:(?P<ticket_id>T\d+)"):
    """Button to close a ticket. Opens modal for reason."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Close",
                style=discord.ButtonStyle.danger,
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
                "Ticket not found.",
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
                "Only the ticket owner or staff can close this ticket.",
                ephemeral=True,
            )


# =============================================================================
# Add User Button
# =============================================================================

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
                "You don't have permission to add users to tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TicketAddUserModal(self.ticket_id))


# =============================================================================
# Reopen Button
# =============================================================================

class ReopenButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_reopen:(?P<ticket_id>T\d+)"):
    """Button to reopen a closed ticket."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Reopen",
                style=discord.ButtonStyle.success,
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

        # Check if user has staff permissions
        if not interaction.user.guild_permissions.manage_messages:
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
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


# =============================================================================
# Transcript Button
# =============================================================================

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
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Transcript",
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
# Info Button
# =============================================================================

class InfoButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_info:(?P<ticket_id>T\d+)"):
    """Button to view detailed ticket information."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Info",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_info:{ticket_id}",
                emoji=INFO_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "InfoButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.followup.send("Ticket not found.", ephemeral=True)
            return

        # Fetch ticket user
        try:
            ticket_user = await bot.fetch_user(ticket["user_id"])
            user_display = f"{ticket_user.mention} (`{ticket_user.name}`)"
        except Exception:
            user_display = f"<@{ticket['user_id']}>"

        # Build info embed
        from src.core.config import EmbedColors
        from src.utils.footer import set_footer

        status = ticket.get("status", "open")
        category = ticket.get("category", "support")
        cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])
        priority = ticket.get("priority", "normal")
        priority_info = PRIORITY_CONFIG.get(priority, PRIORITY_CONFIG["normal"])

        embed = discord.Embed(
            title=f"{INFO_EMOJI} Ticket Information",
            color=EmbedColors.BLUE,
        )

        # Basic Info
        embed.add_field(
            name="Ticket",
            value=f"`#{ticket['ticket_id']}`",
            inline=True,
        )
        embed.add_field(
            name="Status",
            value=f"{STATUS_EMOJI.get(status, '⚪')} {status.title()}",
            inline=True,
        )
        embed.add_field(
            name="Category",
            value=f"{cat_info['emoji']} {cat_info['label']}",
            inline=True,
        )

        # User Info
        embed.add_field(
            name="Created By",
            value=user_display,
            inline=True,
        )
        embed.add_field(
            name="Priority",
            value=f"{priority_info['emoji']} {priority.title()}",
            inline=True,
        )
        embed.add_field(
            name="\u200b",
            value="\u200b",
            inline=True,
        )

        # Timestamps
        if ticket.get("created_at"):
            embed.add_field(
                name="Created",
                value=f"<t:{int(ticket['created_at'])}:F>\n(<t:{int(ticket['created_at'])}:R>)",
                inline=True,
            )

        if ticket.get("claimed_by"):
            embed.add_field(
                name="Claimed By",
                value=f"<@{ticket['claimed_by']}>",
                inline=True,
            )
            if ticket.get("claimed_at"):
                embed.add_field(
                    name="Claimed At",
                    value=f"<t:{int(ticket['claimed_at'])}:R>",
                    inline=True,
                )

        if ticket.get("closed_at"):
            embed.add_field(
                name="Closed At",
                value=f"<t:{int(ticket['closed_at'])}:F>",
                inline=True,
            )
            if ticket.get("closed_by"):
                embed.add_field(
                    name="Closed By",
                    value=f"<@{ticket['closed_by']}>",
                    inline=True,
                )

        # Subject
        if ticket.get("subject"):
            subject = ticket["subject"]
            if len(subject) > 200:
                subject = subject[:197] + "..."
            embed.add_field(
                name="Subject",
                value=subject,
                inline=False,
            )

        # Close reason
        if ticket.get("close_reason"):
            embed.add_field(
                name="Close Reason",
                value=ticket["close_reason"][:200],
                inline=False,
            )

        # User's ticket stats
        user_tickets = bot.ticket_service.db.get_user_tickets(ticket["user_id"], ticket.get("guild_id", 0))
        if user_tickets:
            total = len(user_tickets)
            open_count = sum(1 for t in user_tickets if t["status"] == "open")
            claimed_count = sum(1 for t in user_tickets if t["status"] == "claimed")
            closed_count = sum(1 for t in user_tickets if t["status"] == "closed")
            embed.add_field(
                name="User's Ticket Stats",
                value=f"🎫 Total: **{total}** │ 🟢 Open: **{open_count}** │ 🔵 Claimed: **{claimed_count}** │ 🔴 Closed: **{closed_count}**",
                inline=False,
            )

        set_footer(embed)
        await interaction.followup.send(embed=embed, ephemeral=True)


# =============================================================================
# Transfer Button
# =============================================================================

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
                "You don't have permission to transfer tickets.",
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
                "Cannot transfer a closed ticket.",
                ephemeral=True,
            )
            return

        # Show user select for transfer
        view = TransferSelectView(self.ticket_id, ticket.get("claimed_by"))
        await interaction.response.send_message(
            "Select a staff member to transfer this ticket to:",
            view=view,
            ephemeral=True,
        )


class TransferSelectView(discord.ui.View):
    """View with user select for ticket transfer."""

    def __init__(self, ticket_id: str, current_claimer: int = None):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.current_claimer = current_claimer

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select staff member...",
        min_values=1,
        max_values=1,
    )
    async def user_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.UserSelect,
    ) -> None:
        bot: "AzabBot" = interaction.client
        target = select.values[0]

        # Validate target is staff
        if isinstance(target, discord.Member):
            if not target.guild_permissions.manage_messages:
                await interaction.response.send_message(
                    f"{target.mention} is not a staff member.",
                    ephemeral=True,
                )
                return
        else:
            await interaction.response.send_message(
                "Please select a server member.",
                ephemeral=True,
            )
            return

        # Check if target is same as current
        if self.current_claimer and target.id == self.current_claimer:
            await interaction.response.send_message(
                "This ticket is already claimed by that person.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        success, message = await bot.ticket_service.transfer_ticket(
            ticket_id=self.ticket_id,
            new_staff=target,
            transferred_by=interaction.user,
        )

        if success:
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
            # Disable the view
            self.stop()
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


# =============================================================================
# History Button
# =============================================================================

class HistoryButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_history:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """Button to view user's ticket history."""

    def __init__(self, user_id: int, guild_id: int):
        self.user_id = user_id
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="History",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_history:{user_id}:{guild_id}",
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
                "Only staff can view user history.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Get ticket history
        ticket_history = bot.ticket_service.db.get_user_tickets(self.user_id, self.guild_id)

        # Get moderation history
        mod_history = bot.ticket_service.db.get_user_warnings(self.user_id, self.guild_id)

        # Fetch user info
        try:
            user = await bot.fetch_user(self.user_id)
            user_display = f"{user.display_name} (`{user.name}`)"
            user_avatar = user.display_avatar.url
        except Exception:
            user_display = f"User ID: {self.user_id}"
            user_avatar = None

        # Build history embed with cleaner design
        from src.core.config import EmbedColors
        from src.utils.footer import set_footer
        from src.core.constants import EMOJI_MUTE, EMOJI_BAN, EMOJI_WARN, EMOJI_KICK

        embed = discord.Embed(
            title=f"{HISTORY_EMOJI} User History",
            color=EmbedColors.GOLD,
        )

        if user_avatar:
            embed.set_thumbnail(url=user_avatar)

        embed.add_field(
            name="User",
            value=f"<@{self.user_id}>\n{user_display}",
            inline=True,
        )

        # Ticket stats summary
        if ticket_history:
            total = len(ticket_history)
            open_count = sum(1 for t in ticket_history if t["status"] == "open")
            closed_count = sum(1 for t in ticket_history if t["status"] == "closed")
            embed.add_field(
                name="Ticket Stats",
                value=f"🎫 **{total}** total\n🟢 **{open_count}** open │ 🔴 **{closed_count}** closed",
                inline=True,
            )
        else:
            embed.add_field(
                name="Ticket Stats",
                value="No tickets",
                inline=True,
            )

        # Mod stats summary
        if mod_history:
            warns = sum(1 for m in mod_history if m.get("action_type") == "warn")
            mutes = sum(1 for m in mod_history if m.get("action_type") == "mute")
            bans = sum(1 for m in mod_history if m.get("action_type") == "ban")
            embed.add_field(
                name="Mod Stats",
                value=f"{EMOJI_WARN} **{warns}** │ {EMOJI_MUTE} **{mutes}** │ {EMOJI_BAN} **{bans}**",
                inline=True,
            )
        else:
            embed.add_field(
                name="Mod Stats",
                value="Clean record",
                inline=True,
            )

        # Recent tickets (last 5)
        if ticket_history:
            ticket_lines = []
            for ticket in ticket_history[:5]:
                status_emoji = STATUS_EMOJI.get(ticket["status"], "⚪")
                created = f"<t:{int(ticket['created_at'])}:R>" if ticket.get("created_at") else "?"
                subject = ticket.get("subject", "No subject")[:30]
                if len(ticket.get("subject", "")) > 30:
                    subject += "..."
                ticket_lines.append(
                    f"{status_emoji} `#{ticket['ticket_id']}` {ticket['category'].title()} - {subject} ({created})"
                )
            embed.add_field(
                name="📋 Recent Tickets",
                value="\n".join(ticket_lines) or "None",
                inline=False,
            )

        # Recent mod actions (last 5)
        if mod_history:
            action_emojis = {
                "warn": EMOJI_WARN,
                "mute": EMOJI_MUTE,
                "ban": EMOJI_BAN,
                "kick": EMOJI_KICK,
            }
            mod_lines = []
            for action in mod_history[:5]:
                emoji = action_emojis.get(action.get("action_type", ""), "📝")
                action_type = action.get("action_type", "action").title()
                reason = action.get("reason", "No reason")[:30]
                if len(action.get("reason", "")) > 30:
                    reason += "..."
                timestamp = f"<t:{int(action['timestamp'])}:R>" if action.get("timestamp") else "?"
                mod_lines.append(
                    f"{emoji} **{action_type}** - {reason} ({timestamp})"
                )
            embed.add_field(
                name="⚠️ Recent Mod Actions",
                value="\n".join(mod_lines) or "None",
                inline=False,
            )

        set_footer(embed)
        await interaction.followup.send(embed=embed, ephemeral=True)


# =============================================================================
# Close Request Buttons
# =============================================================================

class CloseApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_cr_accept:(?P<ticket_id>T\d+):(?P<requester_id>\d+)"):
    """Button for staff to approve a close request."""

    def __init__(self, ticket_id: str, requester_id: int = 0):
        self.ticket_id = ticket_id
        self.requester_id = requester_id
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.success,
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


class CloseDenyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_cr_deny:(?P<ticket_id>T\d+):(?P<requester_id>\d+)"):
    """Button for staff to deny a close request."""

    def __init__(self, ticket_id: str, requester_id: int = 0):
        self.ticket_id = ticket_id
        self.requester_id = requester_id
        super().__init__(
            discord.ui.Button(
                label="Deny",
                style=discord.ButtonStyle.danger,
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
                "Only staff can deny close requests.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Clear close request cooldown
        bot.ticket_service._close_request_cooldowns.pop(self.ticket_id, None)

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
        InfoButton,
        TransferButton,
        HistoryButton,
        CloseApproveButton,
        CloseDenyButton,
    )
    logger.tree("Ticket Buttons Registered", [
        ("Buttons", "Claim, Close, AddUser, Reopen, Transcript, Info, Transfer, History, CloseApprove, CloseDeny"),
    ], emoji="🎫")
