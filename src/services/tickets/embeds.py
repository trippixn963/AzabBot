"""
Ticket System Embeds
====================

Embed builder functions for ticket system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Optional

import discord

from src.core.config import EmbedColors, NY_TZ
from src.utils.footer import set_footer

from .constants import (
    TICKET_CATEGORIES,
    STATUS_EMOJI,
    STATUS_COLOR,
    TRANSFER_EMOJI,
)


# =============================================================================
# Control Panel Embed (Main ticket embed that updates in place)
# =============================================================================

def build_control_panel_embed(
    ticket: dict,
    user: Optional[discord.User] = None,
) -> discord.Embed:
    """
    Build the main control panel embed for a ticket.

    This embed is sent once when the ticket is created and
    updated in place as the ticket state changes.

    Args:
        ticket: Ticket data from database
        user: The ticket creator (optional, for mention)

    Returns:
        Discord embed with ticket status and info
    """
    status = ticket.get("status", "open")
    category = ticket.get("category", "support")
    cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])

    # Build status display with all states
    status_display = " → ".join([
        f"**{STATUS_EMOJI[s]} {s.title()}**" if s == status else f"{STATUS_EMOJI[s]} {s.title()}"
        for s in ["open", "claimed", "closed"]
    ])

    embed = discord.Embed(
        title="🎫 Ticket Control Panel",
        color=STATUS_COLOR.get(status, EmbedColors.GREEN),
    )

    # Row 1: Ticket ID, Status, Category
    embed.add_field(
        name="Ticket",
        value=f"`#{ticket['ticket_id']}`",
        inline=True,
    )
    embed.add_field(
        name="Status",
        value=status_display,
        inline=True,
    )
    embed.add_field(
        name="Category",
        value=f"{cat_info['emoji']} {cat_info['label']}",
        inline=True,
    )

    # Row 2: User, Claimed by (if applicable)
    if user:
        embed.add_field(
            name="User",
            value=f"{user.mention}\n`{user.name}`",
            inline=True,
        )
    else:
        embed.add_field(
            name="User",
            value=f"<@{ticket['user_id']}>",
            inline=True,
        )

    if ticket.get("claimed_by"):
        embed.add_field(
            name="Claimed by",
            value=f"<@{ticket['claimed_by']}>",
            inline=True,
        )
    else:
        embed.add_field(
            name="Claimed by",
            value="—",
            inline=True,
        )

    # Row 3: Created, Subject
    created_at = ticket.get("created_at")
    if created_at:
        embed.add_field(
            name="Created",
            value=f"<t:{int(created_at)}:R>",
            inline=True,
        )

    if ticket.get("subject"):
        # Truncate subject if too long
        subject = ticket["subject"]
        if len(subject) > 100:
            subject = subject[:97] + "..."
        embed.add_field(
            name="Subject",
            value=subject,
            inline=False,
        )

    # Add close reason if closed
    if status == "closed" and ticket.get("close_reason"):
        embed.add_field(
            name="Close Reason",
            value=ticket["close_reason"][:200],
            inline=False,
        )

    set_footer(embed)
    return embed


# =============================================================================
# Notification Embeds (Simple, no buttons)
# =============================================================================

def build_welcome_embed(
    user: discord.Member,
    category: str,
    subject: str,
    assigned_text: str,
    wait_time_text: str = "",
) -> discord.Embed:
    """Build welcome message for new ticket."""
    cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])

    embed = discord.Embed(
        description=(
            f"Welcome {user.mention}!\n\n"
            f"{assigned_text}\n"
            f"Please describe your issue in detail.\n\n"
            f"**Subject:** {subject}"
            f"{wait_time_text}"
        ),
        color=cat_info["color"],
    )
    set_footer(embed)
    return embed


def build_claim_notification(
    staff: discord.Member,
) -> discord.Embed:
    """Build notification when ticket is claimed."""
    embed = discord.Embed(
        description=f"✅ {staff.mention} has claimed this ticket and will assist you shortly.",
        color=EmbedColors.BLUE,
    )
    embed.set_thumbnail(url=staff.display_avatar.url)
    set_footer(embed)
    return embed


def build_close_notification(
    closed_by: discord.Member,
    reason: Optional[str] = None,
) -> discord.Embed:
    """Build notification when ticket is closed."""
    description = f"🔒 This ticket has been closed by {closed_by.mention}."
    if reason:
        description += f"\n\n**Reason:** {reason}"

    embed = discord.Embed(
        description=description,
        color=EmbedColors.RED,
    )
    set_footer(embed)
    return embed


def build_reopen_notification(
    reopened_by: discord.Member,
) -> discord.Embed:
    """Build notification when ticket is reopened."""
    embed = discord.Embed(
        description=f"🔓 This ticket has been reopened by {reopened_by.mention}.",
        color=EmbedColors.GREEN,
    )
    set_footer(embed)
    return embed


def build_user_added_notification(
    added_by: discord.Member,
    added_user: discord.Member,
) -> discord.Embed:
    """Build notification when user is added to ticket."""
    embed = discord.Embed(
        description=f"👤 {added_user.mention} has been added to this ticket by {added_by.mention}.",
        color=EmbedColors.BLUE,
    )
    set_footer(embed)
    return embed


def build_transfer_notification(
    new_staff: discord.Member,
    transferred_by: discord.Member,
) -> discord.Embed:
    """Build notification when ticket is transferred."""
    embed = discord.Embed(
        description=f"{TRANSFER_EMOJI} This ticket has been transferred to {new_staff.mention} by {transferred_by.mention}.",
        color=EmbedColors.BLUE,
    )
    set_footer(embed)
    return embed


def build_inactivity_warning(
    user_id: int,
    days_inactive: int,
    days_until_close: int,
) -> discord.Embed:
    """Build inactivity warning embed."""
    embed = discord.Embed(
        title="⚠️ Inactivity Warning",
        description=(
            f"<@{user_id}>, this ticket has been inactive for **{days_inactive} days**.\n\n"
            f"It will be automatically closed in **{days_until_close} days** if no activity occurs.\n\n"
            f"Please send a message if you still need assistance."
        ),
        color=EmbedColors.WARNING,
    )
    set_footer(embed)
    return embed


# =============================================================================
# Close Request Embed
# =============================================================================

def build_close_request_embed(
    requester: discord.Member,
) -> discord.Embed:
    """Build close request embed for staff approval."""
    embed = discord.Embed(
        title="🔒 Close Request",
        description=(
            f"{requester.mention} has requested to close this ticket.\n\n"
            f"A staff member must approve or deny this request."
        ),
        color=EmbedColors.WARNING,
    )
    set_footer(embed)
    return embed


# =============================================================================
# DM Embeds
# =============================================================================

def build_ticket_closed_dm(
    ticket_id: str,
    category: str,
    close_reason: Optional[str],
    closed_by: discord.Member,
    guild_name: str,
) -> discord.Embed:
    """Build DM notification for ticket closure."""
    cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])

    embed = discord.Embed(
        title=f"🎫 Ticket Closed - #{ticket_id}",
        description=(
            f"Your {cat_info['label'].lower()} ticket in **{guild_name}** has been closed.\n\n"
            f"**Closed by:** {closed_by.display_name}"
        ),
        color=EmbedColors.GOLD,
    )

    if close_reason:
        embed.add_field(
            name="Reason",
            value=close_reason[:500],
            inline=False,
        )

    set_footer(embed)
    return embed


def build_ticket_claimed_dm(
    ticket_id: str,
    staff: discord.Member,
    guild_name: str,
) -> discord.Embed:
    """Build DM notification for ticket being claimed."""
    embed = discord.Embed(
        title=f"🎫 Ticket Update - #{ticket_id}",
        description=(
            f"Your ticket in **{guild_name}** has been claimed by **{staff.display_name}**.\n\n"
            f"They will assist you shortly."
        ),
        color=EmbedColors.BLUE,
    )
    set_footer(embed)
    return embed


# =============================================================================
# Panel Embed
# =============================================================================

def build_panel_embed() -> discord.Embed:
    """Build the ticket creation panel embed."""
    embed = discord.Embed(
        title="🎫 Support Tickets",
        description=(
            "Need help? Click a button below to create a ticket.\n\n"
            "**Categories:**\n"
        ),
        color=EmbedColors.GREEN,
    )

    for key, info in TICKET_CATEGORIES.items():
        embed.description += f"{info['emoji']} **{info['label']}** - {info['description']}\n"

    embed.description += "\n*Only one open ticket per user is allowed.*"
    set_footer(embed)
    return embed
