"""
AzabBot - Ticket System Embeds
==============================

Embed builder functions for ticket system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional

import discord

from src.core.config import EmbedColors
from src.utils.mention_resolver import embed_user, embed_mention

from .constants import (
    TICKET_CATEGORIES,
    STATUS_COLOR,
    DELETE_AFTER_CLOSE_DAYS,
)


# =============================================================================
# Control Panel Embed (Main ticket embed that updates in place)
# =============================================================================

def build_control_panel_embed(
    ticket: dict,
    user: Optional[discord.User] = None,
    closed_by: Optional[discord.Member] = None,
    user_ticket_count: Optional[int] = None,
) -> discord.Embed:
    """
    Build the main control panel embed for a ticket.

    Clean, mobile-friendly design using description instead of many fields.
    """
    status = ticket.get("status", "open")
    category = ticket.get("category", "support")
    cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])
    ticket_id = ticket.get("ticket_id", "???")

    # Build description with key info
    lines = []

    # User line
    if user:
        lines.append(f"👤 {embed_mention(user)} (`{user.name}`)")
    else:
        lines.append(f"👤 {embed_user(ticket['user_id'])}")

    # Category and created time on same line
    created_at = ticket.get("created_at")
    if created_at:
        lines.append(f"{cat_info['emoji']} {cat_info['label']} • Created <t:{int(created_at)}:R>")
    else:
        lines.append(f"{cat_info['emoji']} {cat_info['label']}")

    # Claimed by (if claimed)
    if ticket.get("claimed_by"):
        lines.append(f"✋ Claimed by {embed_user(ticket['claimed_by'])}")

    # Subject
    if ticket.get("subject"):
        subject = ticket["subject"]
        if len(subject) > 100:
            subject = subject[:97] + "..."
        lines.append(f"\n**Subject:** `{subject}`")

    # Answers from modal (stored as JSON)
    if ticket.get("answers_json"):
        try:
            import json
            answers = json.loads(ticket["answers_json"])
            for question, answer in answers.items():
                ans = answer if len(answer) <= 200 else answer[:197] + "..."
                lines.append(f"**{question}:** `{ans}`")
        except (json.JSONDecodeError, TypeError):
            pass
    elif ticket.get("description"):
        # Fallback for older tickets without answers_json
        desc = ticket["description"]
        if len(desc) > 300:
            desc = desc[:297] + "..."
        lines.append(f"**Details:** {desc}")

    # Close reason (if closed)
    if status == "closed" and ticket.get("close_reason"):
        lines.append(f"\n**Close Reason:** {ticket['close_reason'][:150]}")

    embed = discord.Embed(
        title=f"🎫 Ticket #{ticket_id}",
        description="\n".join(lines),
        color=STATUS_COLOR.get(status, EmbedColors.GREEN),
    )

    # Thumbnail: always use ticket user's avatar (not closed_by)
    if user:
        embed.set_thumbnail(url=user.display_avatar.url)

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

    # Custom instructions based on category
    if category == "verification":
        description = (
            f"Welcome {embed_mention(user)}!\n\n"
            f"{assigned_text}\n\n"
            f"**Verification Steps:**\n"
            f"1️⃣ A staff member will invite you to a voice channel\n"
            f"2️⃣ You'll need to speak briefly so we can verify\n"
            f"3️⃣ Once verified, you'll receive the appropriate role\n\n"
            f"*If voice verification isn't possible, staff may ask for a selfie with your username and today's date, or a link to your social media.*"
            f"\n\n*{wait_time_text}*" if wait_time_text else ""
        )
    elif category == "partnership":
        description = (
            f"Welcome {embed_mention(user)}!\n\n"
            f"{assigned_text}\n\n"
            f"**Please provide the following:**\n"
            f"1️⃣ Your server name and invite link\n"
            f"2️⃣ Your server's member count\n"
            f"3️⃣ A brief description of your server\n"
            f"4️⃣ What type of partnership you're looking for\n\n"
            f"*We'll review your request and get back to you shortly.*"
            f"\n\n*{wait_time_text}*" if wait_time_text else ""
        )
    elif category == "suggestion":
        description = (
            f"Welcome {embed_mention(user)}!\n\n"
            f"{assigned_text}\n\n"
            f"**Please include:**\n"
            f"1️⃣ A clear description of your suggestion\n"
            f"2️⃣ Why you think this would benefit the server\n"
            f"3️⃣ Any examples or references if applicable\n\n"
            f"*We appreciate your feedback and will review your suggestion!*"
            f"\n\n*{wait_time_text}*" if wait_time_text else ""
        )
    elif category == "appeal":
        description = (
            f"Welcome {embed_mention(user)}!\n\n"
            f"{assigned_text}\n\n"
            f"**Mute Appeal Process:**\n"
            f"1️⃣ Explain why you were muted and what happened\n"
            f"2️⃣ Acknowledge if you broke any rules\n"
            f"3️⃣ Explain why you believe the mute should be removed or reduced\n\n"
            f"⚠️ **Note:** Being rude or dishonest will result in your appeal being denied.\n\n"
            f"**Subject:** {subject}"
            f"\n\n*{wait_time_text}*" if wait_time_text else ""
        )
    else:  # support
        description = (
            f"Welcome {embed_mention(user)}!\n\n"
            f"{assigned_text}\n\n"
            f"**To help us assist you faster:**\n"
            f"1️⃣ Describe your issue in detail\n"
            f"2️⃣ Include any relevant screenshots if needed\n"
            f"3️⃣ Let us know what you've already tried\n\n"
            f"**Subject:** {subject}"
            f"\n\n*{wait_time_text}*" if wait_time_text else ""
        )

    embed = discord.Embed(
        description=description,
        color=cat_info["color"],
    )
    return embed


def build_claim_notification(
    staff: discord.Member,
    stats: Optional[dict] = None,
) -> discord.Embed:
    """Build notification when ticket is claimed."""
    embed = discord.Embed(
        description=f"✅ {embed_mention(staff)} has claimed this ticket and will assist you shortly.",
        color=EmbedColors.GOLD,
    )
    embed.set_thumbnail(url=staff.display_avatar.url)

    # Add staff stats if provided
    if stats:
        claimed = stats.get("claimed", 0)
        embed.add_field(
            name="Tickets Claimed",
            value=f"`{claimed}`",
            inline=True,
        )

    # Add join date
    if staff.joined_at:
        embed.add_field(
            name="Staff Since",
            value=f"<t:{int(staff.joined_at.timestamp())}:D>",
            inline=True,
        )

    return embed


def build_close_notification(
    closed_by: discord.Member,
    reason: Optional[str] = None,
    stats: Optional[dict] = None,
) -> discord.Embed:
    """Build notification when ticket is closed."""
    # Calculate deletion timestamp (DELETE_AFTER_CLOSE_DAYS from now)
    deletion_timestamp = int(time.time()) + (DELETE_AFTER_CLOSE_DAYS * 86400)

    description = f"🔒 This ticket has been closed by {embed_mention(closed_by)}."
    if reason:
        description += f"\n\n**Reason:** {reason}"
    description += f"\n\n🗑️ This thread will be deleted <t:{deletion_timestamp}:R>"

    embed = discord.Embed(
        description=description,
        color=EmbedColors.GOLD,
    )
    embed.set_thumbnail(url=closed_by.display_avatar.url)

    # Add staff stats if provided
    if stats:
        embed.add_field(
            name="Tickets Claimed",
            value=f"`{stats.get('claimed', 0)}`",
            inline=True,
        )

    # Add join date
    if closed_by.joined_at:
        embed.add_field(
            name="Staff Since",
            value=f"<t:{int(closed_by.joined_at.timestamp())}:D>",
            inline=True,
        )

    return embed


def build_reopen_notification(
    reopened_by: discord.Member,
    stats: Optional[dict] = None,
) -> discord.Embed:
    """Build notification when ticket is reopened."""
    embed = discord.Embed(
        description=f"🔓 This ticket has been reopened by {embed_mention(reopened_by)}.",
        color=EmbedColors.GOLD,
    )
    embed.set_thumbnail(url=reopened_by.display_avatar.url)

    # Add staff stats if provided
    if stats:
        embed.add_field(
            name="Tickets Claimed",
            value=f"`{stats.get('claimed', 0)}`",
            inline=True,
        )

    # Add join date
    if reopened_by.joined_at:
        embed.add_field(
            name="Staff Since",
            value=f"<t:{int(reopened_by.joined_at.timestamp())}:D>",
            inline=True,
        )

    return embed


def build_user_added_notification(
    added_by: discord.Member,
    added_user: discord.Member,
) -> discord.Embed:
    """Build notification when user is added to ticket."""
    embed = discord.Embed(
        description=f"👤 {embed_mention(added_user)} has been added to this ticket by {embed_mention(added_by)}.",
        color=EmbedColors.GOLD,
    )
    embed.set_thumbnail(url=added_user.display_avatar.url)

    # User info
    embed.add_field(
        name="User",
        value=f"{embed_mention(added_user)}\n`{added_user.name}`",
        inline=True,
    )

    # Account created
    if added_user.created_at:
        embed.add_field(
            name="Account Created",
            value=f"<t:{int(added_user.created_at.timestamp())}:D>",
            inline=True,
        )

    # Joined server
    if added_user.joined_at:
        embed.add_field(
            name="Joined Server",
            value=f"<t:{int(added_user.joined_at.timestamp())}:D>",
            inline=True,
        )

    return embed


def build_transfer_notification(
    new_staff: discord.Member,
    transferred_by: discord.Member,
    stats: Optional[dict] = None,
) -> discord.Embed:
    """Build notification when ticket is transferred."""
    embed = discord.Embed(
        description=f"🔄 This ticket has been transferred to {embed_mention(new_staff)} by {embed_mention(transferred_by)}.",
        color=EmbedColors.GOLD,
    )
    embed.set_thumbnail(url=new_staff.display_avatar.url)

    # Add new staff stats if provided
    if stats:
        embed.add_field(
            name="Tickets Claimed",
            value=f"`{stats.get('claimed', 0)}`",
            inline=True,
        )

    # Add new staff join date
    if new_staff.joined_at:
        embed.add_field(
            name="Staff Since",
            value=f"<t:{int(new_staff.joined_at.timestamp())}:D>",
            inline=True,
        )

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
            f"{embed_user(user_id)}, this ticket has been inactive for **{days_inactive} days**.\n\n"
            f"It will be automatically closed in **{days_until_close} days** if no activity occurs.\n\n"
            f"Please send a message if you still need assistance."
        ),
        color=EmbedColors.WARNING,
    )
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
            f"{embed_mention(requester)} has requested to close this ticket.\n\n"
            f"A staff member must approve or deny this request."
        ),
        color=EmbedColors.WARNING,
    )
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
        color=EmbedColors.GOLD,
    )
    return embed


# =============================================================================
# Panel Embed
# =============================================================================

def build_panel_embed() -> discord.Embed:
    """Build the ticket panel embed with categories and dropdown."""
    lines = []
    for key, info in TICKET_CATEGORIES.items():
        if info.get("hidden"):
            continue
        lines.append(f"{info['emoji']} **{info['label']}** - {info['description']}")


    embed = discord.Embed(
        description="\n".join(lines),
        color=EmbedColors.GREEN,
    )
    return embed


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "build_control_panel_embed",
    "build_welcome_embed",
    "build_claim_notification",
    "build_close_notification",
    "build_reopen_notification",
    "build_user_added_notification",
    "build_transfer_notification",
    "build_inactivity_warning",
    "build_close_request_embed",
    "build_ticket_closed_dm",
    "build_ticket_claimed_dm",
    "build_panel_embed",
]
