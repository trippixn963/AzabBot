"""
Ticket System Modals
====================

Modal dialogs for ticket creation, closing, and user management.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
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
            max_length=100,
        )
        self.add_item(self.subject)

        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            placeholder="Describe your issue or request in detail...",
            required=True,
            min_length=1,
            max_length=1000,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        try:
            await interaction.response.defer(ephemeral=True)

            bot: "AzabBot" = interaction.client
            if not hasattr(bot, "ticket_service") or not bot.ticket_service:
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
                # Log to interaction webhook
                if hasattr(bot, "interaction_logger") and bot.interaction_logger and ticket_id:
                    ticket = bot.ticket_service.db.get_ticket(ticket_id)
                    thread_id = ticket["thread_id"] if ticket else 0
                    guild_id = interaction.guild.id if interaction.guild else 0
                    await bot.interaction_logger.log_ticket_created(
                        interaction.user, ticket_id, self.category, self.subject.value,
                        thread_id, guild_id
                    )
                await interaction.followup.send(f"✅ {message}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)

        except Exception as e:
            logger.error("Ticket Creation Modal Failed", [
                ("User", f"{interaction.user} ({interaction.user.id})"),
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
            ("User", f"{interaction.user} ({interaction.user.id})"),
            ("Error", str(error)),
        ])
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)[:100]}",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"❌ An error occurred: {str(error)[:100]}",
                    ephemeral=True,
                )
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
            max_length=500,
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

        # Get ticket info before closing
        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        ticket_user = None
        if ticket:
            try:
                ticket_user = await bot.fetch_user(ticket["user_id"])
            except Exception:
                pass

        success, message = await bot.ticket_service.close_ticket(
            ticket_id=self.ticket_id,
            closed_by=interaction.user,
            reason=self.reason.value or None,
        )

        if success:
            # Log to interaction webhook
            if ticket_user and hasattr(bot, "interaction_logger") and bot.interaction_logger:
                await bot.interaction_logger.log_ticket_closed(
                    interaction.user, self.ticket_id, ticket_user, self.reason.value
                )
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
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
            max_length=100,
        )
        self.add_item(self.user_input)

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

        # Parse user ID from input (handles raw ID or mention)
        user_input = self.user_input.value.strip()

        # Extract ID from mention format <@123456789> or <@!123456789>
        mention_match = re.match(r"<@!?(\d+)>", user_input)
        if mention_match:
            user_id = int(mention_match.group(1))
        elif user_input.isdigit():
            user_id = int(user_input)
        else:
            logger.tree("Ticket Add User Failed", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Input", user_input[:50]),
                ("Reason", "Invalid user format"),
            ], emoji="❌")
            await interaction.followup.send(
                "❌ Invalid user. Please enter a user ID or @mention.",
                ephemeral=True,
            )
            return

        # Get the user to add
        try:
            user_to_add = await bot.fetch_user(user_id)
        except discord.NotFound:
            await interaction.followup.send(
                "❌ User not found.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to fetch user: {str(e)[:50]}",
                ephemeral=True,
            )
            return

        # Get member in guild
        if not interaction.guild:
            await interaction.followup.send(
                "❌ This command can only be used in a server.",
                ephemeral=True,
            )
            return

        member = interaction.guild.get_member(user_id)
        if not member:
            await interaction.followup.send(
                "❌ User is not a member of this server.",
                ephemeral=True,
            )
            return

        # Add user to ticket
        success, message = await bot.ticket_service.add_user_to_ticket(
            ticket_id=self.ticket_id,
            user=member,
            added_by=interaction.user,
        )

        if success:
            # Log to interaction webhook
            ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
            ticket_user = None
            if ticket:
                try:
                    ticket_user = await bot.fetch_user(ticket["user_id"])
                except Exception:
                    pass

            if hasattr(bot, "interaction_logger") and bot.interaction_logger and ticket_user:
                await bot.interaction_logger.log_ticket_user_added(
                    interaction.user, self.ticket_id, member
                )
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)
