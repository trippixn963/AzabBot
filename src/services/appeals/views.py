"""
AzabBot - Appeal Views
======================

Discord UI components for the appeal system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.views import CASE_EMOJI, APPROVE_EMOJI, APPEAL_EMOJI, DENY_EMOJI, InfoButton, HistoryButton, UserInfoSelect
from src.core.constants import EMOJI_ID_MODMAIL, EMOJI_ID_TRANSCRIPT

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Appeal Action View (Persistent)
# =============================================================================

class AppealActionView(discord.ui.View):
    """
    Persistent view with control panel for appeals.

    DESIGN:
        Uses custom_id pattern for persistence across bot restarts.
        Only moderators can use action buttons.

    Layout:
        Row 0: User Info dropdown + View Case link
        Row 1: Approve, Deny, Open Ticket/Contact User
    """

    def __init__(self, appeal_id: str, case_id: str, user_id: int, guild_id: int, case_url: Optional[str] = None, action_type: str = "mute"):
        super().__init__(timeout=None)

        # =================================================================
        # Row 0: User Info dropdown + View Case link
        # =================================================================

        self.add_item(UserInfoSelect(user_id, guild_id))

        if case_url:
            self.add_item(discord.ui.Button(
                label="View Case",
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
                url=case_url,
                row=0,
            ))

        # =================================================================
        # Row 1: Action buttons
        # =================================================================

        approve_btn = ApproveAppealButton(appeal_id, case_id)
        approve_btn.row = 1
        self.add_item(approve_btn)

        deny_btn = DenyAppealButton(appeal_id, case_id)
        deny_btn.row = 1
        self.add_item(deny_btn)

        # Add Open Ticket button only for mute appeals (banned users can't be in main server)
        if action_type == "mute":
            ticket_btn = OpenAppealTicketButton(appeal_id, user_id)
            ticket_btn.row = 1
            self.add_item(ticket_btn)
        # Add Contact User button for ban appeals (initiates modmail with banned user)
        elif action_type == "ban":
            contact_btn = ContactBannedUserButton(appeal_id, user_id)
            contact_btn.row = 1
            self.add_item(contact_btn)


class ApproveAppealButton(discord.ui.DynamicItem[discord.ui.Button], template=r"appeal_approve:(?P<appeal_id>[A-Z0-9]+):(?P<case_id>[A-Z0-9]+)"):
    """Persistent approve appeal button."""

    def __init__(self, appeal_id: str, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.secondary,
                custom_id=f"appeal_approve:{appeal_id}:{case_id}",
                emoji=APPROVE_EMOJI,
            )
        )
        self.appeal_id = appeal_id
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "ApproveAppealButton":
        appeal_id = match.group("appeal_id")
        case_id = match.group("case_id")
        return cls(appeal_id, case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle approve button click."""
        logger.tree("Approve Appeal Button Clicked", [
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Appeal ID", self.appeal_id),
            ("Case ID", self.case_id),
        ], emoji="✅")

        # Check permissions - must have moderate_members OR be in allowed user list
        config = get_config()
        allowed_ids = {config.developer_id}
        if config.appeal_allowed_user_ids:
            allowed_ids |= config.appeal_allowed_user_ids

        has_permission = (
            interaction.user.guild_permissions.moderate_members or
            interaction.user.id in allowed_ids
        )

        if not has_permission:
            logger.warning("Appeal Approve Permission Denied", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Appeal ID", self.appeal_id),
            ])
            await interaction.response.send_message(
                "You don't have permission to approve appeals.",
                ephemeral=True,
            )
            return

        # Show modal for reason
        modal = AppealReasonModal(self.appeal_id, self.case_id, "approve")
        await interaction.response.send_modal(modal)


class DenyAppealButton(discord.ui.DynamicItem[discord.ui.Button], template=r"appeal_deny:(?P<appeal_id>[A-Z0-9]+):(?P<case_id>[A-Z0-9]+)"):
    """Persistent deny appeal button."""

    def __init__(self, appeal_id: str, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Deny",
                style=discord.ButtonStyle.secondary,
                custom_id=f"appeal_deny:{appeal_id}:{case_id}",
                emoji=DENY_EMOJI,
            )
        )
        self.appeal_id = appeal_id
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "DenyAppealButton":
        appeal_id = match.group("appeal_id")
        case_id = match.group("case_id")
        return cls(appeal_id, case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle deny button click."""
        logger.tree("Deny Appeal Button Clicked", [
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Appeal ID", self.appeal_id),
            ("Case ID", self.case_id),
        ], emoji="❌")

        # Check permissions - must have moderate_members OR be in allowed user list
        config = get_config()
        allowed_ids = {config.developer_id}
        if config.appeal_allowed_user_ids:
            allowed_ids |= config.appeal_allowed_user_ids

        has_permission = (
            interaction.user.guild_permissions.moderate_members or
            interaction.user.id in allowed_ids
        )

        if not has_permission:
            logger.warning("Appeal Deny Permission Denied", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Appeal ID", self.appeal_id),
            ])
            await interaction.response.send_message(
                "You don't have permission to deny appeals.",
                ephemeral=True,
            )
            return

        # Show modal for reason
        modal = AppealReasonModal(self.appeal_id, self.case_id, "deny")
        await interaction.response.send_modal(modal)


class OpenAppealTicketButton(discord.ui.DynamicItem[discord.ui.Button], template=r"appeal_ticket:(?P<appeal_id>[A-Z0-9]+):(?P<user_id>\d+)"):
    """Persistent button to open a ticket with the appealing user in the main server."""

    def __init__(self, appeal_id: str, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="Open Ticket",
                style=discord.ButtonStyle.secondary,
                custom_id=f"appeal_ticket:{appeal_id}:{user_id}",
                emoji=discord.PartialEmoji(name="modmail", id=EMOJI_ID_MODMAIL),
            )
        )
        self.appeal_id = appeal_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "OpenAppealTicketButton":
        appeal_id = match.group("appeal_id")
        user_id = int(match.group("user_id"))
        return cls(appeal_id, user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        # Check permissions
        config = get_config()
        allowed_ids = {config.developer_id}
        if config.appeal_allowed_user_ids:
            allowed_ids |= config.appeal_allowed_user_ids

        has_permission = (
            interaction.user.guild_permissions.moderate_members or
            interaction.user.id in allowed_ids
        )

        if not has_permission:
            logger.warning("Appeal Ticket Permission Denied", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Appeal ID", self.appeal_id),
            ])
            await interaction.response.send_message(
                "You don't have permission to open appeal tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.followup.send(
                "Ticket service is not available.",
                ephemeral=True,
            )
            return

        # Get the appeal details
        db = get_db()
        appeal = db.get_appeal(self.appeal_id)
        if not appeal:
            await interaction.followup.send(
                "Appeal not found.",
                ephemeral=True,
            )
            return

        # Get the user from the main server
        main_guild = bot.get_guild(config.logging_guild_id)
        if not main_guild:
            await interaction.followup.send(
                "Main server not found.",
                ephemeral=True,
            )
            return

        try:
            member = await main_guild.fetch_member(self.user_id)
        except discord.NotFound:
            await interaction.followup.send(
                "User is not in the main server. They may have left or been banned.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Failed to fetch user: {e}",
                ephemeral=True,
            )
            return

        # Create ticket in main server
        success, message, ticket_id = await bot.ticket_service.create_ticket(
            user=member,
            category="support",
            subject=f"Appeal Discussion - {self.appeal_id}",
            description=f"This ticket was created to discuss appeal **{self.appeal_id}**.\n\nCase ID: `{appeal['case_id']}`",
        )

        if success:
            staff = interaction.user
            logger.tree("Appeal Ticket Created", [
                ("Appeal ID", self.appeal_id),
                ("Ticket ID", ticket_id),
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("User ID", str(member.id)),
                ("Created By", f"{staff.name} ({staff.nick})" if hasattr(staff, 'nick') and staff.nick else staff.name),
                ("Staff ID", str(staff.id)),
            ], emoji="🎫")

            await interaction.followup.send(
                f"✅ {message}\n\nTicket created for appeal discussion.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"❌ Failed to create ticket: {message}",
                ephemeral=True,
            )


class ContactBannedUserButton(discord.ui.DynamicItem[discord.ui.Button], template=r"appeal_contact:(?P<appeal_id>[A-Z0-9]+):(?P<user_id>\d+)"):
    """Persistent button to contact a banned user via modmail to discuss their appeal."""

    def __init__(self, appeal_id: str, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="Contact User",
                style=discord.ButtonStyle.secondary,
                custom_id=f"appeal_contact:{appeal_id}:{user_id}",
                emoji=discord.PartialEmoji(name="transcript", id=EMOJI_ID_TRANSCRIPT),
            )
        )
        self.appeal_id = appeal_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "ContactBannedUserButton":
        appeal_id = match.group("appeal_id")
        user_id = int(match.group("user_id"))
        return cls(appeal_id, user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        # Check permissions
        config = get_config()
        allowed_ids = {config.developer_id}
        if config.appeal_allowed_user_ids:
            allowed_ids |= config.appeal_allowed_user_ids

        has_permission = (
            interaction.user.guild_permissions.moderate_members or
            interaction.user.id in allowed_ids
        )

        if not has_permission:
            logger.warning("Appeal Contact Permission Denied", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Appeal ID", self.appeal_id),
            ])
            await interaction.response.send_message(
                "You don't have permission to contact banned users.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        bot = interaction.client
        if not hasattr(bot, "modmail_service") or not bot.modmail_service:
            await interaction.followup.send(
                "Modmail service is not available.",
                ephemeral=True,
            )
            return

        if not bot.modmail_service.enabled:
            await interaction.followup.send(
                "Modmail service is not enabled.",
                ephemeral=True,
            )
            return

        # Get the appeal details
        db = get_db()
        appeal = db.get_appeal(self.appeal_id)
        if not appeal:
            await interaction.followup.send(
                "Appeal not found.",
                ephemeral=True,
            )
            return

        # Fetch the banned user
        try:
            user = await bot.fetch_user(self.user_id)
        except discord.NotFound:
            await interaction.followup.send(
                "User not found.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Failed to fetch user: {e}",
                ephemeral=True,
            )
            return

        # Create or get existing modmail thread
        thread = await bot.modmail_service.create_thread(user)
        if not thread:
            await interaction.followup.send(
                "Failed to create modmail thread.",
                ephemeral=True,
            )
            return

        # Send initial message to the user
        appeal_embed = discord.Embed(
            title="📬 Staff Wants to Discuss Your Appeal",
            description=(
                f"A staff member wants to discuss your ban appeal **{self.appeal_id}**.\n\n"
                "You can reply to this message to communicate with the moderation team. "
                "All your messages will be forwarded to staff."
            ),
            color=EmbedColors.INFO,
            timestamp=datetime.now(NY_TZ)
        )
        set_footer(appeal_embed)

        try:
            await user.send(embed=appeal_embed)
        except discord.Forbidden:
            await interaction.followup.send(
                "Could not DM the user - they may have DMs disabled.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Failed to send DM: {e}",
                ephemeral=True,
            )
            return

        # Post notification in the modmail thread
        thread_embed = discord.Embed(
            title="Appeal Discussion Started",
            description=(
                f"**{interaction.user.mention}** initiated a discussion about appeal **{self.appeal_id}**.\n\n"
                f"The user has been notified and can now reply via DM."
            ),
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ)
        )
        thread_embed.add_field(name="Appeal ID", value=self.appeal_id, inline=True)
        thread_embed.add_field(name="Case ID", value=appeal["case_id"], inline=True)
        set_footer(thread_embed)

        try:
            await thread.send(embed=thread_embed)
        except discord.HTTPException:
            pass

        staff = interaction.user
        logger.tree("Appeal Contact Initiated", [
            ("Appeal ID", self.appeal_id),
            ("User", user.name),
            ("User ID", str(user.id)),
            ("Initiated By", f"{staff.name} ({staff.nick})" if hasattr(staff, 'nick') and staff.nick else staff.name),
            ("Staff ID", str(staff.id)),
            ("Thread", str(thread.id)),
        ], emoji="📬")

        await interaction.followup.send(
            f"✅ Modmail initiated with **{user}**.\n\n"
            f"The user has been DMed and can now reply. Check the modmail thread to continue the conversation.",
            ephemeral=True,
        )


# =============================================================================
# Appeal Reason Modal
# =============================================================================

class AppealReasonModal(discord.ui.Modal):
    """Modal for entering appeal resolution reason."""

    def __init__(self, appeal_id: str, case_id: str, action: str):
        title = "Approve Appeal" if action == "approve" else "Deny Appeal"
        super().__init__(title=title)
        self.appeal_id = appeal_id
        self.case_id = case_id
        self.action = action

        self.reason = discord.ui.TextInput(
            label="Reason (optional)",
            style=discord.TextStyle.paragraph,
            placeholder="Enter a reason for this decision...",
            required=False,
            max_length=500,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        logger.tree("Appeal Reason Modal Submitted", [
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Appeal ID", self.appeal_id),
            ("Case ID", self.case_id),
            ("Action", self.action.upper()),
        ], emoji="📋")

        await interaction.response.defer(ephemeral=True)

        # Get appeal service from bot
        bot = interaction.client
        if not hasattr(bot, "appeal_service") or not bot.appeal_service:
            await interaction.followup.send(
                "Appeal service is not available.",
                ephemeral=True,
            )
            return

        reason = self.reason.value.strip() if self.reason.value else None

        if self.action == "approve":
            success, message = await bot.appeal_service.approve_appeal(
                self.appeal_id,
                interaction.user,
                reason,
            )
        else:
            success, message = await bot.appeal_service.deny_appeal(
                self.appeal_id,
                interaction.user,
                reason,
            )

        await interaction.followup.send(message, ephemeral=True)


# =============================================================================
# Submit Appeal Button (for case embeds)
# =============================================================================

class SubmitAppealButton(discord.ui.DynamicItem[discord.ui.Button], template=r"submit_appeal:(?P<case_id>[A-Z0-9]+):(?P<user_id>\d+)"):
    """
    Persistent button on case embeds to submit an appeal.

    Only the affected user can use this button.
    """

    def __init__(self, case_id: str, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="Appeal",
                style=discord.ButtonStyle.secondary,
                custom_id=f"submit_appeal:{case_id}:{user_id}",
                emoji=APPEAL_EMOJI,
            )
        )
        self.case_id = case_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "SubmitAppealButton":
        case_id = match.group("case_id")
        user_id = int(match.group("user_id"))
        return cls(case_id, user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle appeal button click from DM."""
        logger.tree("Appeal Button Clicked", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Case ID", self.case_id),
            ("Channel", "DM" if isinstance(interaction.channel, discord.DMChannel) else str(interaction.channel)),
        ], emoji="📝")

        # This button should only appear in the original case thread
        # and only the affected user can submit
        if interaction.user.id != self.user_id:
            logger.warning("Appeal Button Wrong User", [
                ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Expected User", str(self.user_id)),
                ("Case ID", self.case_id),
            ])
            await interaction.response.send_message(
                "You can only appeal your own cases.",
                ephemeral=True,
            )
            return

        # Check if appeal service is available
        bot = interaction.client
        if not hasattr(bot, "appeal_service") or not bot.appeal_service:
            logger.warning("Appeal Service Unavailable", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Case ID", self.case_id),
            ])
            await interaction.response.send_message(
                "Appeal system is not available.",
                ephemeral=True,
            )
            return

        # Check eligibility
        can_appeal, reason, _ = bot.appeal_service.can_appeal(self.case_id)
        if not can_appeal:
            logger.tree("Appeal Eligibility Failed", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Case ID", self.case_id),
                ("Reason", reason or "Unknown"),
            ], emoji="⚠️")
            await interaction.response.send_message(
                f"Cannot submit appeal: {reason}",
                ephemeral=True,
            )
            return

        # Show appeal modal
        modal = SubmitAppealModal(self.case_id)
        await interaction.response.send_modal(modal)


class SubmitAppealModal(discord.ui.Modal, title="Submit Appeal"):
    """Modal for submitting an appeal."""

    def __init__(self, case_id: str):
        super().__init__()
        self.case_id = case_id

        self.reason = discord.ui.TextInput(
            label="Why should your punishment be removed?",
            style=discord.TextStyle.paragraph,
            placeholder="Explain why you believe your ban/mute should be reversed...",
            required=True,
            min_length=20,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        logger.tree("Submit Appeal Modal Submitted", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Case ID", self.case_id),
            ("Channel", "DM" if isinstance(interaction.channel, discord.DMChannel) else str(interaction.channel)),
        ], emoji="📝")

        await interaction.response.defer(ephemeral=True)

        bot = interaction.client
        if not hasattr(bot, "appeal_service") or not bot.appeal_service:
            await interaction.followup.send(
                "Appeal system is not available.",
                ephemeral=True,
            )
            return

        success, message, appeal_id = await bot.appeal_service.create_appeal(
            case_id=self.case_id,
            user=interaction.user,
            reason=self.reason.value,
        )

        if success:
            await interaction.followup.send(
                f"✅ {message}\n\nYour appeal has been submitted to the moderation team for review.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"❌ {message}",
                ephemeral=True,
            )


# =============================================================================
# Views Using Dynamic Items (must be after DynamicItem definitions)
# =============================================================================

class AppealApprovedView(discord.ui.View):
    """View for appeal approved notification (user info + history)."""

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.add_item(InfoButton(user_id, guild_id))
        self.add_item(HistoryButton(user_id, guild_id))


class AppealDeniedView(discord.ui.View):
    """View for appeal denied notification (ticket link)."""

    def __init__(self, ticket_channel_id: int, guild_id: int):
        super().__init__(timeout=None)
        # Add link button to ticket channel
        self.add_item(discord.ui.Button(
            label="Contact Staff",
            style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{guild_id}/{ticket_channel_id}",
            emoji="🎫",
        ))


# =============================================================================
# Setup Function (for persistent views)
# =============================================================================

def setup_appeal_views(bot: "AzabBot") -> None:
    """Register appeal dynamic items for persistence."""
    bot.add_dynamic_items(
        ApproveAppealButton,
        DenyAppealButton,
        SubmitAppealButton,
        OpenAppealTicketButton,
        ContactBannedUserButton,
    )
    logger.debug("Appeal Views Registered")
