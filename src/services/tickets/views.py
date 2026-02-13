"""
AzabBot - Ticket System Views
=============================

View classes for ticket panel and control panel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import get_config
from src.core.logger import logger
from src.views import UserInfoSelect
from src.views.constants import CASE_EMOJI

from .buttons import (
    ClaimButton,
    CloseButton,
    AddUserButton,
    ReopenButton,
    TransferButton,
    CloseApproveButton,
    CloseDenyButton,
)
from .constants import TICKET_CATEGORIES, TRANSCRIPT_EMOJI
from .modals import TicketCreateModal

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Ticket Panel View (Category Selection)
# =============================================================================

class TicketCategorySelect(discord.ui.Select):
    """Dropdown select menu for ticket category selection."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=info["label"],
                value=key,
                description=info["description"],
                emoji=info["emoji"],
            )
            for key, info in TICKET_CATEGORIES.items()
            if not info.get("hidden", False)  # Skip hidden categories like "appeal"
        ]

        super().__init__(
            placeholder="Select a category...",
            options=options,
            custom_id="tkt_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.values:
            await interaction.response.send_message(
                "No category selected. Please try again.",
                ephemeral=True,
            )
            return

        category = self.values[0]
        logger.tree("Ticket Category Selected", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Category", category),
        ], emoji="🎫")
        await interaction.response.send_modal(TicketCreateModal(category))


class TicketPanelView(discord.ui.View):
    """
    View for the ticket creation panel.
    Displays a dropdown menu for selecting ticket category.
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())


class TicketPanelSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"tkt_select"):
    """Dynamic item for ticket panel select menu (persistence)."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=info["label"],
                value=key,
                description=info["description"],
                emoji=info["emoji"],
            )
            for key, info in TICKET_CATEGORIES.items()
            if not info.get("hidden", False)  # Skip hidden categories like "appeal"
        ]

        super().__init__(
            discord.ui.Select(
                placeholder="Select a category...",
                options=options,
                custom_id="tkt_select",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match,
    ) -> "TicketPanelSelect":
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        category = self.item.values[0]
        logger.tree("Ticket Category Selected", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Category", category),
        ], emoji="🎫")
        await interaction.response.send_modal(TicketCreateModal(category))


# =============================================================================
# Booster Unjail Button (for prison intro embed)
# =============================================================================

class BoosterUnjailButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"unjail_card:(?P<user_id>\d+):(?P<guild_id>\d+)"
):
    """
    Persistent button on prison intro embed for boosters to unjail themselves.

    Only boosters can see and use this button (once per day).
    Removes the muted role and marks the mute as resolved.
    """

    def __init__(self, user_id: int, guild_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Unjail",
                style=discord.ButtonStyle.secondary,
                custom_id=f"unjail_card:{user_id}:{guild_id}",
                emoji="<:unlock:1455200891866190040>",
            )
        )
        self.user_id = user_id
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "BoosterUnjailButton":
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Handle unjail button click - removes mute for boosters.

        Validates:
        - Correct user (only muted user can use their own card)
        - Booster status (must still be boosting)
        - Daily usage limit (one per day, resets midnight EST)
        """
        logger.tree("Unjail Button Clicked", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Expected User", str(self.user_id)),
            ("Guild ID", str(self.guild_id)),
        ], emoji="🔓")

        # Only the muted user can use this
        if interaction.user.id != self.user_id:
            logger.warning("Unjail Button Wrong User", [
                ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Expected User", str(self.user_id)),
            ])
            await interaction.response.send_message(
                "You can only use your own Unjail card.",
                ephemeral=True,
            )
            return

        # Ensure we have a Member object
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This button can only be used in the server.",
                ephemeral=True,
            )
            return

        member = interaction.user

        # Verify booster status (in case they lost boost since embed was sent)
        if member.premium_since is None:
            logger.warning("Unjail Card Non-Booster Attempt", [
                ("User", f"{member.name} ({member.id})"),
            ])
            await interaction.response.send_message(
                "Only server boosters can use the Unjail card.",
                ephemeral=True,
            )
            return

        # Check daily usage
        from src.core.database import get_db
        db = get_db()

        if not db.can_use_unjail_card(member.id, self.guild_id):
            # Get cooldown time
            reset_at = db.get_unjail_card_cooldown(member.id, self.guild_id)
            if reset_at:
                reset_ts = int(reset_at)
                await interaction.response.send_message(
                    f"You've already used your daily Unjail card.\n"
                    f"Resets <t:{reset_ts}:R> (midnight EST).",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "You've already used your daily Unjail card.",
                    ephemeral=True,
                )
            return

        await interaction.response.defer(ephemeral=True)

        # Get mute info for logging
        mute_record = db.get_active_mute(member.id, self.guild_id)
        mute_reason = mute_record["reason"] if mute_record else None

        # Record usage atomically (prevents double-click race condition)
        if not db.use_unjail_card(member.id, self.guild_id, mute_reason):
            await interaction.followup.send(
                "Failed to use Unjail card. Please try again.",
                ephemeral=True,
            )
            return

        # Get muted role and remove it
        config = get_config()
        muted_role = interaction.guild.get_role(config.muted_role_id)

        if not muted_role:
            logger.error("Unjail Card Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Reason", "Muted role not found"),
            ])
            await interaction.followup.send(
                "Failed to unjail - muted role not found. Please contact staff.",
                ephemeral=True,
            )
            return

        if muted_role not in member.roles:
            # Already unmuted somehow
            await interaction.followup.send(
                "You're not currently muted!",
                ephemeral=True,
            )
            return

        try:
            # Remove the muted role
            await member.remove_roles(
                muted_role,
                reason=f"Booster Unjail Card used by {member.name}"
            )

            # Update database - mark mute as resolved
            db.remove_mute(
                user_id=member.id,
                guild_id=self.guild_id,
                moderator_id=member.id,  # Self-unmute
                reason="Booster Unjail Card",
            )

            # Log to permanent audit log
            db.log_moderation_action(
                user_id=member.id,
                guild_id=self.guild_id,
                moderator_id=member.id,
                action_type="unmute",
                action_source="unjail_card",
                reason="Booster Unjail Card",
                details={"original_reason": mute_reason},
            )

            logger.tree("Booster Unjail Success", [
                ("User", f"{member.name} ({member.id})"),
                ("Original Reason", (mute_reason or "None")[:50]),
            ], emoji="🔓")

            await interaction.followup.send(
                "<:unlock:1455200891866190040> **Unjail Card Used!**\n"
                "You have been released from prison.\n"
                "Your daily card will reset at midnight EST.",
                ephemeral=True,
            )

            # -----------------------------------------------------------------
            # Post to Prison Channel (advertisement for boosting)
            # -----------------------------------------------------------------
            try:
                if config.prison_channel_ids:
                    prison_channel = interaction.guild.get_channel(
                        next(iter(config.prison_channel_ids))
                    )
                    if prison_channel:
                        await prison_channel.send(
                            f"<:unlock:1455200891866190040> **{member.mention} used their Booster Unjail Card!**\n"
                            f"-# Server boosters get a free \"Get Out of Jail\" card every day. "
                            f"Boost the server to unlock this perk!"
                        )
            except Exception as e:
                logger.warning("Failed to post unjail announcement", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Error", str(e)[:50]),
                ])

            # -----------------------------------------------------------------
            # Add Note to Case Thread
            # -----------------------------------------------------------------
            try:
                bot = interaction.client
                config = get_config()
                if hasattr(bot, "case_log_service") and bot.case_log_service:
                    # Find case - check ops guild first (where cases are created)
                    case_data = None
                    for gid in [config.ops_guild_id, self.guild_id]:
                        if gid:
                            case_data = db.get_active_mute_case(member.id, gid)
                            if case_data and case_data.get("thread_id"):
                                break
                    if case_data and case_data.get("thread_id"):
                        # Thread is always in ops server
                        ops_guild = bot.get_guild(config.ops_guild_id)
                        if ops_guild:
                            thread = ops_guild.get_thread(case_data["thread_id"])
                            if not thread:
                                thread = await ops_guild.fetch_channel(case_data["thread_id"])
                        else:
                            thread = None
                        if thread:
                            await thread.send(
                                f"<:unlock:1455200891866190040> **Unjail Card Used**\n"
                                f"{member.mention} used their daily Booster Unjail Card to release themselves from prison."
                            )
            except Exception as e:
                logger.warning("Failed to post case note", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Error", str(e)[:50]),
                ])

            # -----------------------------------------------------------------
            # Update Original Embed
            # -----------------------------------------------------------------
            try:
                original_message = interaction.message
                if original_message:
                    embed = original_message.embeds[0] if original_message.embeds else None
                    if embed:
                        embed.title = "<:unlock:1455200891866190040> Released (Unjail Card)"
                        embed.color = 0x57F287  # Green
                        await original_message.edit(embed=embed, view=None)
            except Exception as e:
                logger.warning("Failed to update unjail embed", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Error", str(e)[:50]),
                ])

            # -----------------------------------------------------------------
            # Send Release Announcement to General Chat
            # -----------------------------------------------------------------
            try:
                # Import here to avoid circular import (prison handler imports services)
                from src.handlers.prison import send_release_announcement, ReleaseType

                await send_release_announcement(
                    bot=interaction.client,
                    member=member,
                    release_type=ReleaseType.BOOSTER_CARD,
                )
                # Note: send_release_announcement handles its own logging
            except Exception as e:
                logger.warning("Release Announcement Failed", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Error", str(e)[:50]),
                ])

        except discord.Forbidden:
            logger.error("Unjail Card Failed (Permissions)", [
                ("User", f"{member.name} ({member.id})"),
                ("Guild", str(self.guild_id)),
            ])
            await interaction.followup.send(
                "Failed to remove muted role - missing permissions. Please contact staff.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            logger.error("Unjail Card Failed (HTTP)", [
                ("User", f"{member.name} ({member.id})"),
                ("Guild", str(self.guild_id)),
                ("Error", str(e)[:100]),
            ])
            await interaction.followup.send(
                f"Failed to unjail: {e}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Unjail Card Failed (Unexpected)", [
                ("User", f"{member.name} ({member.id})"),
                ("Guild", str(self.guild_id)),
                ("Error", str(e)[:100]),
            ])
            try:
                await interaction.followup.send(
                    "An unexpected error occurred. Please try again or contact staff.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass  # Already failed, nothing more we can do


# =============================================================================
# Mute Appeal Button (for prison intro embed)
# =============================================================================

class MuteAppealButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mute_appeal:(?P<case_id>[A-Z0-9]+):(?P<user_id>\d+)"
):
    """
    Persistent button on prison intro embed to open an appeal ticket.

    Only the muted user can use this button.
    Creates a ticket with category "appeal" and pre-filled mute information.
    """

    def __init__(self, case_id: str, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Appeal",
                style=discord.ButtonStyle.secondary,
                custom_id=f"mute_appeal:{case_id}:{user_id}",
                emoji=TICKET_CATEGORIES["appeal"]["emoji"],
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
    ) -> "MuteAppealButton":
        case_id = match.group("case_id")
        user_id = int(match.group("user_id"))
        return cls(case_id, user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle appeal button click - creates an appeal ticket."""
        logger.tree("Mute Appeal Button Clicked", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Case ID", self.case_id),
            ("Expected User", str(self.user_id)),
        ], emoji="📝")

        # Only the muted user can appeal
        if interaction.user.id != self.user_id:
            logger.warning("Mute Appeal Button Wrong User", [
                ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Expected User", str(self.user_id)),
                ("Case ID", self.case_id),
            ])
            await interaction.response.send_message(
                "You can only appeal your own mutes.",
                ephemeral=True,
            )
            return

        # Check if ticket service is available
        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            logger.warning("Ticket Service Unavailable", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Case ID", self.case_id),
            ])
            await interaction.response.send_message(
                "Ticket system is not available. Please contact staff directly.",
                ephemeral=True,
            )
            return

        # Ensure we have a Member object
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This button can only be used in the server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Create the appeal ticket
        subject = f"Mute Appeal - Case #{self.case_id}"
        description = (
            f"This ticket was created to appeal mute case `{self.case_id}`.\n\n"
            f"Please explain why you believe your mute should be removed or reduced."
        )

        try:
            success, message, ticket_id = await bot.ticket_service.create_ticket(
                user=interaction.user,
                category="appeal",
                subject=subject,
                description=description,
                case_id=self.case_id,
            )

            if success:
                logger.tree("Mute Appeal Ticket Created", [
                    ("User", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Case ID", self.case_id),
                    ("Ticket ID", ticket_id or "Unknown"),
                ], emoji="✅")

                await interaction.followup.send(
                    f"✅ Your appeal ticket has been created! Check the ticket channel to discuss your case with staff.",
                    ephemeral=True,
                )
            else:
                logger.warning("Mute Appeal Ticket Failed", [
                    ("User", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Case ID", self.case_id),
                    ("Reason", message[:100]),
                ])
                await interaction.followup.send(
                    f"❌ Could not create appeal ticket: {message}",
                    ephemeral=True,
                )

        except Exception as e:
            logger.error("Mute Appeal Ticket Error", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Case ID", self.case_id),
                ("Error", str(e)[:100]),
            ])
            await interaction.followup.send(
                "❌ An error occurred while creating your appeal ticket. Please try again or contact staff directly.",
                ephemeral=True,
            )


# =============================================================================
# Ticket Control Panel View
# =============================================================================

class TicketControlPanelView(discord.ui.View):
    """
    Main control panel view for a ticket.

    This view is sent once when the ticket is created and
    updated in place as the ticket state changes.

    Layout:
        Row 0: User Info dropdown (Info, Avatar, History for ticket owner)
        Row 1: Action buttons based on status + Case button for appeals

    Button visibility is based on ticket status:
    - open: Claim, Close, AddUser, [Case for appeals]
    - claimed: Close, Transfer, AddUser, [Case for appeals]
    - closed: Reopen, Transcript, [Case for appeals]
    """

    def __init__(
        self,
        ticket_id: str,
        status: str,
        user_id: int,
        guild_id: int,
        case_url: Optional[str] = None,
        transcript_token: Optional[str] = None,
    ):
        super().__init__(timeout=None)

        self.ticket_id = ticket_id
        self.status = status
        self.user_id = user_id
        self.guild_id = guild_id
        self.case_url = case_url  # Pre-computed URL for appeal tickets
        self.transcript_token = transcript_token  # Stored token for transcript access

        self._add_components()

    def _add_components(self) -> None:
        """Add components based on current ticket status."""
        # =================================================================
        # Row 0: User Info dropdown (ticket owner's moderation info)
        # =================================================================

        self.add_item(UserInfoSelect(self.user_id, self.guild_id))

        # =================================================================
        # Row 1: Action buttons based on status
        # =================================================================

        if self.status == "open":
            # Open tickets: Claim, Close, AddUser
            claim_btn = ClaimButton(self.ticket_id)
            claim_btn.row = 1
            self.add_item(claim_btn)

            close_btn = CloseButton(self.ticket_id)
            close_btn.row = 1
            self.add_item(close_btn)

            add_user_btn = AddUserButton(self.ticket_id)
            add_user_btn.row = 1
            self.add_item(add_user_btn)

        elif self.status == "claimed":
            # Claimed tickets: Close, Transfer, AddUser
            close_btn = CloseButton(self.ticket_id)
            close_btn.row = 1
            self.add_item(close_btn)

            transfer_btn = TransferButton(self.ticket_id)
            transfer_btn.row = 1
            self.add_item(transfer_btn)

            add_user_btn = AddUserButton(self.ticket_id)
            add_user_btn.row = 1
            self.add_item(add_user_btn)

        elif self.status == "closed":
            # Closed tickets: Reopen, Transcript (direct link)
            reopen_btn = ReopenButton(self.ticket_id)
            reopen_btn.row = 1
            self.add_item(reopen_btn)

            # Direct link button for transcript with stored token (no login required)
            config = get_config()
            if config.transcript_base_url and self.transcript_token:
                self.add_item(discord.ui.Button(
                    label="Transcript",
                    style=discord.ButtonStyle.link,
                    url=f"{config.transcript_base_url}/{self.ticket_id}?token={self.transcript_token}",
                    emoji=TRANSCRIPT_EMOJI,
                    row=1,
                ))

        # =================================================================
        # Case button for appeal tickets (same row as action buttons)
        # =================================================================
        if self.case_url:
            self.add_item(discord.ui.Button(
                label="Case",
                style=discord.ButtonStyle.link,
                url=self.case_url,
                emoji=CASE_EMOJI,
                row=1,
            ))

    @classmethod
    def from_ticket(cls, ticket: dict) -> "TicketControlPanelView":
        """Create view from ticket database record."""
        # Build case URL for appeal tickets (DB lookup here, not in constructor)
        case_url = None
        case_id = ticket.get("case_id")
        if ticket.get("category") == "appeal" and case_id:
            try:
                from src.core.database import get_db
                config = get_config()
                db = get_db()
                case_data = db.get_case(case_id)
                if case_data and case_data.get("thread_id") and config.main_guild_id:
                    case_url = f"https://discord.com/channels/{config.main_guild_id}/{case_data['thread_id']}"
            except (KeyError, TypeError):
                pass

        return cls(
            ticket_id=ticket["ticket_id"],
            status=ticket.get("status", "open"),
            user_id=ticket["user_id"],
            guild_id=ticket.get("guild_id", 0),
            case_url=case_url,
            transcript_token=ticket.get("transcript_token"),
        )


# =============================================================================
# Close Request View
# =============================================================================

class CloseRequestView(discord.ui.View):
    """
    View for close request approval.

    When a ticket owner requests to close, this view is shown
    for staff to approve or deny.
    """

    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        self.add_item(CloseApproveButton(ticket_id))
        self.add_item(CloseDenyButton(ticket_id))


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "TicketCategorySelect",
    "TicketPanelView",
    "TicketPanelSelect",
    "MuteAppealButton",
    "BoosterUnjailButton",
    "TicketControlPanelView",
    "CloseRequestView",
]
