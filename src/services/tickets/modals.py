"""
AzabBot - Ticket System Modals
==============================

Modal dialogs for ticket creation, closing, and user management.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.constants import MODAL_FIELD_SHORT, MODAL_FIELD_MEDIUM, MODAL_FIELD_LONG
from .constants import TICKET_CATEGORIES

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Create Ticket Modal
# =============================================================================

class TicketCreateModal(discord.ui.Modal, title="Create Ticket"):
    """Modal for creating a new ticket."""

    def __init__(self, category: str):
        super().__init__()
        self.category = category

        cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])

        self.subject = discord.ui.TextInput(
            label="Subject",
            style=discord.TextStyle.short,
            placeholder=f"Brief summary of your {cat_info['label'].lower()} request...",
            required=True,
            min_length=1,
            max_length=MODAL_FIELD_SHORT,
        )
        self.add_item(self.subject)

        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            placeholder="Describe your issue or request in detail...",
            required=True,
            min_length=1,
            max_length=MODAL_FIELD_LONG,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        try:
            await interaction.response.defer(ephemeral=True)

            bot: "AzabBot" = interaction.client
            if not hasattr(bot, "ticket_service") or not bot.ticket_service:
                logger.error("Ticket Service Check Failed", [
                    ("Has Attribute", str(hasattr(bot, "ticket_service"))),
                    ("Value", str(getattr(bot, "ticket_service", "MISSING"))),
                    ("Bot Type", type(bot).__name__),
                ])
                await interaction.followup.send(
                    "Ticket system is not available.",
                    ephemeral=True,
                )
                return

            success, message, ticket_id = await bot.ticket_service.create_ticket(
                user=interaction.user,
                category=self.category,
                subject=self.subject.value,
                description=self.description.value,
            )

            if success:
                logger.tree("Ticket Created (Modal)", [
                    ("Ticket ID", ticket_id),
                    ("User", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Category", self.category),
                    ("Subject", self.subject.value[:50]),
                ], emoji="🎫")
                await interaction.followup.send(f"✅ {message}", ephemeral=True)
            else:
                logger.error("Ticket Creation Failed (Modal)", [
                    ("User", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Category", self.category),
                    ("Reason", message),
                ])
                await interaction.followup.send(f"❌ {message}", ephemeral=True)

        except Exception as e:
            logger.error("Ticket Creation Modal Failed", [
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("ID", str(interaction.user.id)),
                ("Category", self.category),
                ("Error", str(e)),
            ])
            try:
                await interaction.followup.send(
                    f"❌ An error occurred while creating your ticket: {str(e)[:100]}",
                    ephemeral=True,
                )
            except Exception:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        """Handle modal errors."""
        logger.error("Ticket Modal Error", [
            ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("ID", str(interaction.user.id)),
            ("Error", str(error)),
        ])
        try:
            response_done = False
            try:
                response_done = interaction.response.is_done()
            except discord.HTTPException:
                response_done = True  # Assume done if we can't check

            if not response_done:
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)[:100]}",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"❌ An error occurred: {str(error)[:100]}",
                    ephemeral=True,
                )
        except discord.HTTPException:
            pass
        except Exception:
            pass


# =============================================================================
# Close Ticket Modal
# =============================================================================

class TicketCloseModal(discord.ui.Modal, title="Close Ticket"):
    """Modal for closing a ticket with a reason."""

    def __init__(self, ticket_id: str):
        super().__init__()
        self.ticket_id = ticket_id

        self.reason = discord.ui.TextInput(
            label="Close Reason",
            style=discord.TextStyle.paragraph,
            placeholder="Why is this ticket being closed? (optional)",
            required=False,
            max_length=MODAL_FIELD_MEDIUM,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        await interaction.response.defer(ephemeral=True)

        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.followup.send(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        success, message = await bot.ticket_service.close_ticket(
            ticket_id=self.ticket_id,
            closed_by=interaction.user,
            reason=self.reason.value or None,
        )

        if success:
            logger.tree("Ticket Closed (Modal)", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", (self.reason.value or "None")[:50]),
            ], emoji="🔒")
            # No ephemeral message - the channel embed is sufficient
        else:
            logger.error("Ticket Close Failed (Modal)", [
                ("Ticket ID", self.ticket_id),
                ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", message),
            ])
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


# =============================================================================
# Add User Modal
# =============================================================================

class TicketAddUserModal(discord.ui.Modal, title="Add User to Ticket"):
    """Modal for adding a user to a ticket thread."""

    def __init__(self, ticket_id: str):
        super().__init__()
        self.ticket_id = ticket_id

        self.user_input = discord.ui.TextInput(
            label="User ID or @Mention",
            style=discord.TextStyle.short,
            placeholder="Enter user ID (e.g., 123456789) or @mention",
            required=True,
            min_length=1,
            max_length=MODAL_FIELD_SHORT,
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Parse user ID from input (handles raw ID or mention)
        user_input = self.user_input.value.strip()

        # Extract ID from mention format <@123456789> or <@!123456789>
        mention_match = re.match(r"<@!?(\d+)>", user_input)
        if mention_match:
            user_id = int(mention_match.group(1))
        elif user_input.isdigit():
            user_id = int(user_input)
        else:
            logger.error("Ticket Add User Failed", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("ID", str(interaction.user.id)),
                ("Input", user_input[:50]),
                ("Reason", "Invalid user format"),
            ])
            await interaction.response.send_message(
                "❌ Invalid user. Please enter a user ID or @mention.",
                ephemeral=True,
            )
            return

        # Get the user to add
        try:
            user_to_add = await bot.fetch_user(user_id)
        except discord.NotFound:
            await interaction.response.send_message(
                "❌ User not found.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to fetch user: {str(e)[:50]}",
                ephemeral=True,
            )
            return

        # Get member in guild
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.",
                ephemeral=True,
            )
            return

        member = interaction.guild.get_member(user_id)
        if not member:
            await interaction.response.send_message(
                "❌ User is not a member of this server.",
                ephemeral=True,
            )
            return

        # Defer silently for successful case (channel embed is enough)
        await interaction.response.defer()

        # Add user to ticket
        success, message = await bot.ticket_service.add_user_to_ticket(
            ticket_id=self.ticket_id,
            user=member,
            added_by=interaction.user,
        )

        if success:
            logger.tree("User Added to Ticket (Modal)", [
                ("Ticket ID", self.ticket_id),
                ("Added User", f"{member.name} ({member.id})"),
                ("Added By", f"{interaction.user.name} ({interaction.user.id})"),
            ], emoji="➕")
            # No followup - the channel embed is sufficient
        else:
            logger.error("Add User Failed (Modal)", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{member.name} ({member.id})"),
                ("Added By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Reason", message),
            ])
            await interaction.followup.send(f"❌ {message}", ephemeral=True)
