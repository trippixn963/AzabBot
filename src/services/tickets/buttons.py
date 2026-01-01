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
from src.core.config import get_config
from .constants import (
    APPROVE_EMOJI,
    DENY_EMOJI,
    LOCK_EMOJI,
    UNLOCK_EMOJI,
    TRANSCRIPT_EMOJI,
    EXTEND_EMOJI,
    INFO_EMOJI,
    TRANSFER_EMOJI,
    TICKET_CATEGORIES,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


def _is_ticket_staff(user: discord.Member) -> bool:
    """Check if user is ticket staff (has manage_messages OR is developer)."""
    config = get_config()
    # Developer can always access
    if config.developer_id and user.id == config.developer_id:
        return True
    # Check for manage_messages permission
    return user.guild_permissions.manage_messages


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
        is_developer = config.developer_id and interaction.user.id == config.developer_id
        if ticket and interaction.user.id == ticket["user_id"] and not is_developer:
            await interaction.response.send_message(
                "Only staff can claim tickets.",
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

        is_staff = _is_ticket_staff(interaction.user)
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

        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)

        # Check if user has staff permissions (or is developer)
        if not _is_ticket_staff(interaction.user):
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
# Info Button (with dropdown for User Info / Criminal History)
# =============================================================================

class InfoButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_info:(?P<ticket_id>T\d+)"):
    """Button to view user info and criminal history via dropdown."""

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

        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message(
                "Ticket not found.",
                ephemeral=True,
            )
            return

        # Show dropdown to select info type
        view = InfoSelectView(
            ticket_id=self.ticket_id,
            user_id=ticket["user_id"],
            guild_id=ticket.get("guild_id", interaction.guild.id),
        )
        await interaction.response.send_message(
            "Select information to view:",
            view=view,
            ephemeral=True,
        )


class InfoSelectView(discord.ui.View):
    """View with dropdown for selecting User Info or Criminal History."""

    def __init__(self, ticket_id: str, user_id: int, guild_id: int):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.select(
        placeholder="Choose info type...",
        options=[
            discord.SelectOption(
                label="User Info",
                value="user_info",
                description="Account age, join date, ticket stats",
                emoji="👤",
            ),
            discord.SelectOption(
                label="Criminal History",
                value="criminal_history",
                description="Warns, mutes, bans with details",
                emoji="⚠️",
            ),
        ],
    )
    async def info_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        bot: "AzabBot" = interaction.client
        await interaction.response.defer(ephemeral=True)

        try:
            choice = select.values[0]

            if choice == "user_info":
                embed = await self._build_user_info_embed(bot, interaction.guild)
            else:
                embed = await self._build_criminal_history_embed(bot)

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error("Info Select Failed", [
                ("Ticket", self.ticket_id),
                ("User ID", str(self.user_id)),
                ("Choice", select.values[0] if select.values else "none"),
                ("Error", str(e)[:100]),
            ])
            await interaction.followup.send(
                f"Failed to load information: {str(e)[:100]}",
                ephemeral=True,
            )
        # Don't stop the view - allow multiple selections until timeout

    async def _build_user_info_embed(
        self,
        bot: "AzabBot",
        guild: discord.Guild,
    ) -> discord.Embed:
        """Build user info embed with account age, join date, etc."""
        from src.core.config import EmbedColors
        from src.utils.footer import set_footer
        from datetime import datetime, timezone

        # Fetch user
        try:
            user = await bot.fetch_user(self.user_id)
        except Exception:
            user = None

        # Get member for join date
        member = guild.get_member(self.user_id) if guild else None

        embed = discord.Embed(
            title="👤 User Information",
            color=EmbedColors.GREEN,
        )

        if user:
            embed.set_thumbnail(url=user.display_avatar.url)

            # Username
            embed.add_field(
                name="User",
                value=f"{user.mention}\n`{user.name}`",
                inline=True,
            )

            # User ID
            embed.add_field(
                name="ID",
                value=f"`{user.id}`",
                inline=True,
            )

            # Account Created
            created_at = user.created_at
            now = datetime.now(timezone.utc)
            age_days = (now - created_at).days

            if age_days < 30:
                age_str = f"{age_days} day{'s' if age_days != 1 else ''}"
            elif age_days < 365:
                months = age_days // 30
                age_str = f"{months} month{'s' if months != 1 else ''}"
            else:
                years = age_days // 365
                remaining_months = (age_days % 365) // 30
                if remaining_months > 0:
                    age_str = f"{years}y {remaining_months}mo"
                else:
                    age_str = f"{years} year{'s' if years != 1 else ''}"

            embed.add_field(
                name="Account Age",
                value=f"**{age_str}**\n<t:{int(created_at.timestamp())}:D>",
                inline=True,
            )
        else:
            embed.add_field(
                name="User",
                value=f"<@{self.user_id}>",
                inline=True,
            )

        # Server Join Date (if member is in guild)
        if member and member.joined_at:
            join_days = (datetime.now(timezone.utc) - member.joined_at).days
            embed.add_field(
                name="Joined Server",
                value=f"<t:{int(member.joined_at.timestamp())}:D>\n({join_days} days ago)",
                inline=True,
            )
        else:
            embed.add_field(
                name="Joined Server",
                value="Not in server",
                inline=True,
            )

        # Ticket Stats
        ticket_history = bot.ticket_service.db.get_user_tickets(self.user_id, self.guild_id)
        if ticket_history:
            total = len(ticket_history)
            open_count = sum(1 for t in ticket_history if t["status"] == "open")
            claimed_count = sum(1 for t in ticket_history if t["status"] == "claimed")
            closed_count = sum(1 for t in ticket_history if t["status"] == "closed")
            embed.add_field(
                name="Ticket Stats",
                value=(
                    f"🎫 **{total}** total\n"
                    f"🟢 {open_count} open │ 🔵 {claimed_count} claimed │ 🔴 {closed_count} closed"
                ),
                inline=True,
            )
        else:
            embed.add_field(
                name="Ticket Stats",
                value="No previous tickets",
                inline=True,
            )

        # Mod Stats Summary
        cases = bot.ticket_service.db.get_user_cases(self.user_id, self.guild_id, limit=100)
        if cases:
            warns = sum(1 for c in cases if c.get("action_type") == "warn")
            mutes = sum(1 for c in cases if c.get("action_type") == "mute")
            bans = sum(1 for c in cases if c.get("action_type") == "ban")
            embed.add_field(
                name="Mod Record",
                value=f"⚠️ {warns} warns │ 🔇 {mutes} mutes │ 🔨 {bans} bans",
                inline=False,
            )
        else:
            embed.add_field(
                name="Mod Record",
                value="✅ Clean record",
                inline=False,
            )

        set_footer(embed)
        return embed

    async def _build_criminal_history_embed(self, bot: "AzabBot") -> discord.Embed:
        """Build criminal history embed with warns, mutes, bans."""
        from src.core.config import EmbedColors
        from src.utils.footer import set_footer

        # Fetch user for thumbnail
        try:
            user = await bot.fetch_user(self.user_id)
            user_display = f"{user.mention} (`{user.name}`)"
            avatar_url = user.display_avatar.url
        except Exception:
            user_display = f"<@{self.user_id}>"
            avatar_url = None

        embed = discord.Embed(
            title="⚠️ Criminal History",
            color=EmbedColors.GOLD,
        )

        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        embed.add_field(
            name="User",
            value=user_display,
            inline=False,
        )

        # Get all cases
        cases = bot.ticket_service.db.get_user_cases(self.user_id, self.guild_id, limit=25)

        if not cases:
            embed.description = "✅ No moderation history found. Clean record!"
            set_footer(embed)
            return embed

        # Count by type
        warns = [c for c in cases if c.get("action_type") == "warn"]
        mutes = [c for c in cases if c.get("action_type") == "mute"]
        bans = [c for c in cases if c.get("action_type") == "ban"]

        # Summary
        embed.add_field(
            name="Summary",
            value=f"⚠️ **{len(warns)}** warns │ 🔇 **{len(mutes)}** mutes │ 🔨 **{len(bans)}** bans",
            inline=False,
        )

        # Recent Warns (last 5)
        if warns:
            warn_lines = []
            for case in warns[:5]:
                reason = case.get("reason", "No reason")
                if len(reason) > 40:
                    reason = reason[:37] + "..."
                mod_id = case.get("moderator_id")
                created = case.get("created_at")
                timestamp = f"<t:{int(created)}:R>" if created else "?"
                warn_lines.append(
                    f"• `{case['case_id']}` {reason}\n  └ by <@{mod_id}> {timestamp}"
                )
            embed.add_field(
                name=f"⚠️ Warns ({len(warns)} total)",
                value="\n".join(warn_lines) if warn_lines else "None",
                inline=False,
            )

        # Recent Mutes (last 5)
        if mutes:
            mute_lines = []
            for case in mutes[:5]:
                reason = case.get("reason", "No reason")
                if len(reason) > 40:
                    reason = reason[:37] + "..."
                mod_id = case.get("moderator_id")
                created = case.get("created_at")
                timestamp = f"<t:{int(created)}:R>" if created else "?"
                duration = case.get("duration_seconds")
                dur_str = ""
                if duration:
                    if duration >= 86400:
                        dur_str = f" ({duration // 86400}d)"
                    elif duration >= 3600:
                        dur_str = f" ({duration // 3600}h)"
                    else:
                        dur_str = f" ({duration // 60}m)"
                mute_lines.append(
                    f"• `{case['case_id']}`{dur_str} {reason}\n  └ by <@{mod_id}> {timestamp}"
                )
            embed.add_field(
                name=f"🔇 Mutes ({len(mutes)} total)",
                value="\n".join(mute_lines) if mute_lines else "None",
                inline=False,
            )

        # Recent Bans (last 5)
        if bans:
            ban_lines = []
            for case in bans[:5]:
                reason = case.get("reason", "No reason")
                if len(reason) > 40:
                    reason = reason[:37] + "..."
                mod_id = case.get("moderator_id")
                created = case.get("created_at")
                timestamp = f"<t:{int(created)}:R>" if created else "?"
                ban_lines.append(
                    f"• `{case['case_id']}` {reason}\n  └ by <@{mod_id}> {timestamp}"
                )
            embed.add_field(
                name=f"🔨 Bans ({len(bans)} total)",
                value="\n".join(ban_lines) if ban_lines else "None",
                inline=False,
            )

        set_footer(embed)
        return embed


# =============================================================================
# Transfer Button
# =============================================================================

def _get_ticket_staff_ids(config) -> set:
    """Get all allowed ticket staff user IDs from config."""
    staff_ids = set()
    if config.ticket_support_user_ids:
        staff_ids.update(config.ticket_support_user_ids)
    if config.ticket_partnership_user_id:
        staff_ids.add(config.ticket_partnership_user_id)
    if config.ticket_suggestion_user_id:
        staff_ids.add(config.ticket_suggestion_user_id)
    return staff_ids


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
        view = TransferSelectView(self.ticket_id, options)
        await interaction.response.send_message(
            "Select a staff member to transfer this ticket to:",
            view=view,
            ephemeral=True,
        )


class TransferSelectView(discord.ui.View):
    """View with select for ticket transfer."""

    def __init__(self, ticket_id: str, options: list):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id

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

        success, message = await bot.ticket_service.transfer_ticket(
            ticket_id=self.ticket_id,
            new_staff=target,
            transferred_by=interaction.user,
        )

        if success:
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
            self.stop()
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


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

        # Check if user has staff permissions (or is developer)
        if not _is_ticket_staff(interaction.user):
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
        CloseApproveButton,
        CloseDenyButton,
    )
    logger.tree("Ticket Buttons Registered", [
        ("Buttons", "Claim, Close, AddUser, Reopen, Transcript, Info, Transfer, CloseApprove, CloseDeny"),
    ], emoji="🎫")
