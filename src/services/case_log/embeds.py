"""
Case Log Embeds
===============

Embed builders for case log messages.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Optional, List

import discord

from src.core.config import EmbedColors, NY_TZ

from .utils import format_age
from .constants import (
    NEW_ACCOUNT_WARNING_DAYS,
    SUSPICIOUS_ACCOUNT_DAYS,
)


# =============================================================================
# Mute Embed
# =============================================================================

def build_mute_embed(
    user: discord.Member,
    moderator: discord.Member,
    duration: str,
    reason: Optional[str] = None,
    mute_count: int = 1,
    is_extension: bool = False,
    evidence: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> discord.Embed:
    """
    Build a mute action embed.

    Args:
        user: The user being muted.
        moderator: The moderator who issued the mute.
        duration: Duration display string.
        reason: Optional reason for the mute.
        mute_count: The mute number for this user.
        is_extension: Whether this is a mute extension.
        evidence: Optional evidence link or description.
        expires_at: Optional expiry datetime for non-permanent mutes.

    Returns:
        Discord Embed for the mute action.
    """
    if is_extension:
        title = "🔇 Mute Extended"
    elif mute_count > 1:
        title = f"🔇 User Muted (Mute #{mute_count})"
    else:
        title = "🔇 User Muted"

    embed = discord.Embed(
        title=title,
        color=EmbedColors.ERROR,
        timestamp=datetime.now(NY_TZ),
    )
    embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Muted By", value=f"`{moderator.display_name}`", inline=True)
    embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

    # Expires field (for non-permanent mutes)
    if expires_at:
        embed.add_field(name="Expires", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True)
    else:
        embed.add_field(name="Expires", value="`Never`", inline=True)

    # Account Age with warning for new accounts
    now = datetime.now(NY_TZ)
    created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
    account_age_days = (now - created_at).days
    age_str = format_age(created_at, now)

    if account_age_days < NEW_ACCOUNT_WARNING_DAYS:
        embed.add_field(name="Account Age", value=f"`{age_str}` ⚠️", inline=True)
    elif account_age_days < SUSPICIOUS_ACCOUNT_DAYS:
        embed.add_field(name="Account Age", value=f"`{age_str}` ⚡", inline=True)
    else:
        embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

    # Previous Mutes count
    previous_mutes = mute_count - 1 if mute_count > 1 else 0
    embed.add_field(name="Previous Mutes", value=f"`{previous_mutes}`", inline=True)

    if reason:
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

    # Evidence: link to the evidence message in the case thread
    if evidence:
        embed.add_field(name="Evidence", value=f"[View Evidence]({evidence})", inline=False)

    return embed


# =============================================================================
# Timeout Embed
# =============================================================================

def build_timeout_embed(
    user: discord.Member,
    mod_name: str,
    duration: str,
    until: datetime,
    reason: Optional[str] = None,
    mute_count: int = 1,
    moderator: Optional[discord.Member] = None,
    evidence_url: Optional[str] = None,
) -> discord.Embed:
    """
    Build a timeout action embed.

    Args:
        user: The user being timed out.
        mod_name: Display name of the moderator.
        duration: Duration display string.
        until: When the timeout expires.
        reason: Optional reason for the timeout.
        mute_count: The mute number for this user.
        moderator: Optional moderator member object for author icon.
        evidence_url: Optional URL to evidence message.

    Returns:
        Discord Embed for the timeout action.
    """
    if mute_count > 1:
        title = f"⏰ User Timed Out (Mute #{mute_count})"
    else:
        title = "⏰ User Timed Out"

    embed = discord.Embed(
        title=title,
        color=EmbedColors.WARNING,
        timestamp=datetime.now(NY_TZ),
    )
    if moderator:
        embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Timed Out By", value=f"`{mod_name}`", inline=True)
    embed.add_field(name="Duration", value=f"`{duration}`", inline=True)
    embed.add_field(name="Expires", value=f"<t:{int(until.timestamp())}:R>", inline=True)

    # Account Age with warning for new accounts
    now = datetime.now(NY_TZ)
    created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
    account_age_days = (now - created_at).days
    age_str = format_age(created_at, now)

    if account_age_days < NEW_ACCOUNT_WARNING_DAYS:
        embed.add_field(name="Account Age", value=f"`{age_str}` ⚠️", inline=True)
    elif account_age_days < SUSPICIOUS_ACCOUNT_DAYS:
        embed.add_field(name="Account Age", value=f"`{age_str}` ⚡", inline=True)
    else:
        embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

    if reason:
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

    if evidence_url:
        embed.add_field(name="Evidence", value=f"[View Evidence]({evidence_url})", inline=False)

    return embed


# =============================================================================
# Warn Embed
# =============================================================================

def build_warn_embed(
    user: discord.Member,
    moderator: discord.Member,
    reason: Optional[str] = None,
    active_warns: int = 1,
    total_warns: int = 1,
    evidence: Optional[str] = None,
    mute_count: int = 0,
    ban_count: int = 0,
) -> discord.Embed:
    """
    Build a warning action embed.

    Args:
        user: The user being warned.
        moderator: The moderator who issued the warning.
        reason: Optional reason for the warning.
        active_warns: Active (non-expired) warning count.
        total_warns: Total warning count (all time).
        evidence: Optional evidence link or description.
        mute_count: Previous mute count for context.
        ban_count: Previous ban count for context.

    Returns:
        Discord Embed for the warning action.
    """
    if active_warns > 1:
        title = f"⚠️ User Warned (Warning #{active_warns})"
    else:
        title = "⚠️ User Warned"

    embed = discord.Embed(
        title=title,
        color=EmbedColors.WARNING,
        timestamp=datetime.now(NY_TZ),
    )
    embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Warned By", value=f"`{moderator.display_name}`", inline=True)

    # Show active vs total if there are expired warnings
    if active_warns != total_warns:
        embed.add_field(name="Warnings", value=f"`{active_warns}` active (`{total_warns}` total)", inline=True)
    else:
        embed.add_field(name="Warning #", value=f"`{active_warns}`", inline=True)

    # Account Age with warning for new accounts
    now = datetime.now(NY_TZ)
    created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
    account_age_days = (now - created_at).days
    age_str = format_age(created_at, now)

    if account_age_days < NEW_ACCOUNT_WARNING_DAYS:
        embed.add_field(name="Account Age", value=f"`{age_str}` ⚠️", inline=True)
    elif account_age_days < SUSPICIOUS_ACCOUNT_DAYS:
        embed.add_field(name="Account Age", value=f"`{age_str}` ⚡", inline=True)
    else:
        embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

    # Previous mute/ban counts for context
    if mute_count > 0 or ban_count > 0:
        embed.add_field(name="Previous Mutes", value=f"`{mute_count}`", inline=True)
        embed.add_field(name="Previous Bans", value=f"`{ban_count}`", inline=True)

    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    else:
        embed.add_field(name="Reason", value="*Not provided*", inline=False)

    # Evidence: link to the evidence message in the case thread
    if evidence:
        embed.add_field(name="Evidence", value=f"[View Evidence]({evidence})", inline=False)

    return embed


# =============================================================================
# Unmute Embed
# =============================================================================

def build_unmute_embed(
    moderator: discord.Member,
    reason: Optional[str] = None,
    user_avatar_url: Optional[str] = None,
    time_served: Optional[str] = None,
    original_duration: Optional[str] = None,
    original_moderator_name: Optional[str] = None,
) -> discord.Embed:
    """
    Build an unmute action embed.

    Args:
        moderator: The moderator who issued the unmute.
        reason: Optional reason for the unmute.
        user_avatar_url: Avatar URL of the unmuted user.
        time_served: How long the user was muted for.
        original_duration: Original mute duration.
        original_moderator_name: Name of the mod who issued the mute.

    Returns:
        Discord Embed for the unmute action.
    """
    embed = discord.Embed(
        title="🔊 User Unmuted",
        color=EmbedColors.SUCCESS,
        timestamp=datetime.now(NY_TZ),
    )
    embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
    if user_avatar_url:
        embed.set_thumbnail(url=user_avatar_url)
    embed.add_field(name="Unmuted By", value=f"`{moderator.display_name}`", inline=True)

    # Time served (how long they were muted)
    if time_served:
        embed.add_field(name="Was Muted For", value=f"`{time_served}`", inline=True)

    # Original duration
    if original_duration:
        embed.add_field(name="Original Duration", value=f"`{original_duration}`", inline=True)

    # Originally muted by
    if original_moderator_name:
        embed.add_field(name="Originally Muted By", value=f"`{original_moderator_name}`", inline=True)

    if reason:
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

    return embed


# =============================================================================
# Expired Embed
# =============================================================================

def build_expired_embed(
    user_avatar_url: Optional[str] = None,
) -> discord.Embed:
    """
    Build a mute expired (auto-unmute) embed.

    Args:
        user_avatar_url: Avatar URL of the user whose mute expired.

    Returns:
        Discord Embed for the expiry.
    """
    embed = discord.Embed(
        title="⏰ Mute Expired (Auto-Unmute)",
        color=EmbedColors.INFO,
        timestamp=datetime.now(NY_TZ),
    )
    if user_avatar_url:
        embed.set_thumbnail(url=user_avatar_url)

    return embed


# =============================================================================
# Ban Embed
# =============================================================================

def build_ban_embed(
    user: discord.User,
    moderator: discord.Member,
    reason: Optional[str] = None,
    ban_count: int = 1,
    evidence: Optional[str] = None,
) -> discord.Embed:
    """
    Build a ban action embed.

    Args:
        user: The user being banned.
        moderator: The moderator who issued the ban.
        reason: Optional reason for the ban.
        ban_count: The ban number for this user.
        evidence: Optional evidence link.

    Returns:
        Discord Embed for the ban action.
    """
    if ban_count > 1:
        title = f"🔨 User Banned (Ban #{ban_count})"
    else:
        title = "🔨 User Banned"

    embed = discord.Embed(
        title=title,
        color=EmbedColors.ERROR,
        timestamp=datetime.now(NY_TZ),
    )
    embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)

    # Handle avatar URL for both Member and User types
    avatar_url = user.display_avatar.url if hasattr(user, 'display_avatar') else user.default_avatar.url
    embed.set_thumbnail(url=avatar_url)

    embed.add_field(name="Banned By", value=f"`{moderator.display_name}`", inline=True)
    embed.add_field(name="Duration", value="`Permanent`", inline=True)

    # Previous bans
    if ban_count > 1:
        embed.add_field(name="Previous Bans", value=f"`{ban_count - 1}`", inline=True)

    if reason:
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

    if evidence:
        embed.add_field(name="Evidence", value=f"[View Evidence]({evidence})", inline=False)

    return embed


# =============================================================================
# Unban Embed
# =============================================================================

def build_unban_embed(
    moderator: discord.Member,
    reason: Optional[str] = None,
    user_avatar_url: Optional[str] = None,
    time_banned: Optional[str] = None,
) -> discord.Embed:
    """
    Build an unban action embed.

    Args:
        moderator: The moderator who issued the unban.
        reason: Optional reason for the unban.
        user_avatar_url: Avatar URL of the unbanned user.
        time_banned: How long the user was banned.

    Returns:
        Discord Embed for the unban action.
    """
    embed = discord.Embed(
        title="🔓 User Unbanned",
        color=EmbedColors.SUCCESS,
        timestamp=datetime.now(NY_TZ),
    )
    embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
    if user_avatar_url:
        embed.set_thumbnail(url=user_avatar_url)
    embed.add_field(name="Unbanned By", value=f"`{moderator.display_name}`", inline=True)

    if time_banned:
        embed.add_field(name="Was Banned For", value=f"`{time_banned}`", inline=True)

    if reason:
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

    return embed


# =============================================================================
# Forbid Embed
# =============================================================================

def build_forbid_embed(
    user: discord.Member,
    moderator: discord.Member,
    restrictions: List[str],
    reason: Optional[str] = None,
    duration: Optional[str] = None,
) -> discord.Embed:
    """Build a forbid action embed."""
    # Restriction display info
    restriction_info = {
        "reactions": ("🚫", "Add Reactions"),
        "attachments": ("📎", "Send Attachments"),
        "voice": ("🔇", "Join Voice"),
        "streaming": ("📺", "Stream/Screenshare"),
        "embeds": ("🔗", "Embed Links"),
        "threads": ("🧵", "Create Threads"),
        "external_emojis": ("😀", "External Emojis"),
        "stickers": ("🎨", "Stickers"),
    }

    embed = discord.Embed(
        title="🚫 User Restricted",
        color=EmbedColors.WARNING,
        timestamp=datetime.now(NY_TZ),
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(
        name="User",
        value=f"{user.mention}\n`{user.id}`",
        inline=True,
    )
    embed.add_field(
        name="Moderator",
        value=f"{moderator.mention}\n`{moderator.id}`",
        inline=True,
    )
    embed.add_field(
        name="Duration",
        value=duration or "Permanent",
        inline=True,
    )

    # Build restrictions list
    restrictions_text = []
    for r in restrictions:
        if r in restriction_info:
            emoji, display = restriction_info[r]
            restrictions_text.append(f"{emoji} {display}")
        else:
            restrictions_text.append(f"• {r}")

    embed.add_field(
        name="Restrictions Applied",
        value="\n".join(restrictions_text) or "None",
        inline=False,
    )

    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    else:
        embed.add_field(name="Reason", value="_No reason provided_", inline=False)

    return embed


# =============================================================================
# Unforbid Embed
# =============================================================================

def build_unforbid_embed(
    user: discord.Member,
    moderator: discord.Member,
    restrictions: List[str],
) -> discord.Embed:
    """Build an unforbid action embed."""
    restriction_info = {
        "reactions": ("🚫", "Add Reactions"),
        "attachments": ("📎", "Send Attachments"),
        "voice": ("🔇", "Join Voice"),
        "streaming": ("📺", "Stream/Screenshare"),
        "embeds": ("🔗", "Embed Links"),
        "threads": ("🧵", "Create Threads"),
        "external_emojis": ("😀", "External Emojis"),
        "stickers": ("🎨", "Stickers"),
    }

    embed = discord.Embed(
        title="✅ Restrictions Removed",
        color=EmbedColors.SUCCESS,
        timestamp=datetime.now(NY_TZ),
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(
        name="User",
        value=f"{user.mention}\n`{user.id}`",
        inline=True,
    )
    embed.add_field(
        name="Moderator",
        value=f"{moderator.mention}\n`{moderator.id}`",
        inline=True,
    )

    # Build restrictions list
    restrictions_text = []
    for r in restrictions:
        if r in restriction_info:
            emoji, display = restriction_info[r]
            restrictions_text.append(f"{emoji} {display}")
        else:
            restrictions_text.append(f"• {r}")

    embed.add_field(
        name="Restrictions Removed",
        value="\n".join(restrictions_text) or "None",
        inline=False,
    )

    return embed


# =============================================================================
# Profile Embed
# =============================================================================

def build_profile_embed(
    user: discord.Member,
    previous_names: List[str] = None,
    mute_count: int = 0,
    ban_count: int = 0,
) -> discord.Embed:
    """
    Build a user profile embed for case threads.

    Args:
        user: The Discord member.
        previous_names: List of previous usernames.
        mute_count: Number of mutes.
        ban_count: Number of bans.

    Returns:
        Discord Embed with user profile info.
    """
    now = datetime.now(NY_TZ)

    embed = discord.Embed(
        title="📋 User Profile",
        color=EmbedColors.INFO,
        timestamp=now,
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(name="Username", value=f"`{user.name}`", inline=True)
    embed.add_field(name="Display Name", value=f"`{user.display_name}`", inline=True)
    embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)

    # Discord joined date
    discord_joined = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
    embed.add_field(name="Discord Joined", value=f"<t:{int(discord_joined.timestamp())}:D>", inline=True)

    # Server joined date
    if user.joined_at:
        server_joined = user.joined_at.replace(tzinfo=NY_TZ) if user.joined_at.tzinfo is None else user.joined_at
        embed.add_field(name="Server Joined", value=f"<t:{int(server_joined.timestamp())}:D>", inline=True)

    # Account age
    age_str = format_age(discord_joined, now)
    embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

    # Previous names
    if previous_names:
        names_str = ", ".join(f"`{name}`" for name in previous_names[:3])
        embed.add_field(name="Previous Names", value=names_str, inline=False)

    # Stats
    if mute_count > 0 or ban_count > 0:
        embed.add_field(name="Total Mutes", value=f"`{mute_count}`", inline=True)
        embed.add_field(name="Total Bans", value=f"`{ban_count}`", inline=True)

    return embed


# =============================================================================
# Event Embeds
# =============================================================================

def build_mute_evasion_embed(
    member: discord.Member,
) -> discord.Embed:
    """Build an embed for mute evasion (rejoin while muted)."""
    embed = discord.Embed(
        title="⚠️ Rejoined While Muted",
        description="User rejoined the server with an active mute. Muted role has been re-applied.",
        color=EmbedColors.WARNING,
        timestamp=datetime.now(NY_TZ),
    )

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Rejoin • ID: {member.id}")

    return embed


def build_vc_violation_embed(
    display_name: str,
    channel_name: str,
    avatar_url: Optional[str] = None,
) -> discord.Embed:
    """Build an embed for voice channel violation by muted user."""
    embed = discord.Embed(
        title="🔇 Voice Channel Violation",
        description="User attempted to join a voice channel while muted. They have been disconnected and given a 1-hour timeout.",
        color=EmbedColors.ERROR,
        timestamp=datetime.now(NY_TZ),
    )

    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(
        name="Attempted Channel",
        value=f"`{channel_name}`",
        inline=True,
    )
    embed.add_field(
        name="Action Taken",
        value="`1 hour timeout`",
        inline=True,
    )

    return embed


def build_member_left_embed(
    display_name: str,
    muted_duration: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> discord.Embed:
    """Build an embed for member leaving while muted."""
    embed = discord.Embed(
        title="🚪 Left While Muted",
        description="User left the server while still muted.",
        color=EmbedColors.WARNING,
        timestamp=datetime.now(NY_TZ),
    )

    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    if muted_duration:
        embed.add_field(
            name="Was Muted For",
            value=f"`{muted_duration}`",
            inline=True,
        )

    return embed


# =============================================================================
# Control Panel Embed
# =============================================================================

# Action type display info
ACTION_DISPLAY = {
    "mute": ("🔇", "Mute"),
    "warn": ("⚠️", "Warning"),
    "ban": ("🔨", "Ban"),
    "timeout": ("⏰", "Timeout"),
    "forbid": ("🚫", "Restriction"),
}

# Status display info
STATUS_DISPLAY = {
    "open": ("🟢", "Active", EmbedColors.ERROR),
    "approved": ("✅", "Approved", EmbedColors.SUCCESS),
    "resolved": ("✅", "Resolved", EmbedColors.SUCCESS),
    "expired": ("⏰", "Expired", EmbedColors.INFO),
}


def build_control_panel_embed(
    case: dict,
    user: Optional[discord.Member] = None,
    moderator: Optional[discord.Member] = None,
    status: str = "open",
    expires_at: Optional[datetime] = None,
) -> discord.Embed:
    """
    Build the persistent control panel embed for a case.

    Args:
        case: Case data dictionary.
        user: The target user (optional).
        moderator: The moderator who created the case (optional).
        status: Case status (open, resolved, expired).
        expires_at: When the punishment expires (for mutes/timeouts).

    Returns:
        Discord Embed for the control panel.
    """
    action_type = case.get("action_type", "unknown")
    case_id = case.get("case_id", "????")

    # Get action display info
    action_emoji, action_label = ACTION_DISPLAY.get(action_type, ("📋", action_type.title()))

    # Get status display info
    status_emoji, status_label, color = STATUS_DISPLAY.get(status, ("❓", "Unknown", EmbedColors.INFO))

    embed = discord.Embed(
        title=f"🎛️ Case Control Panel",
        color=color,
        timestamp=datetime.now(NY_TZ),
    )

    # Set thumbnail to user avatar if available
    if user:
        embed.set_thumbnail(url=user.display_avatar.url)

    # Row 1: Case ID and Action Type
    embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
    embed.add_field(name="Action", value=f"{action_emoji} {action_label}", inline=True)
    embed.add_field(name="Status", value=f"{status_emoji} {status_label}", inline=True)

    # Row 2: User info
    if user:
        embed.add_field(name="User", value=f"{user.mention}", inline=True)
    else:
        user_id = case.get("user_id")
        if user_id:
            embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)

    # Moderator who took action
    if moderator:
        embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)
    else:
        mod_id = case.get("moderator_id")
        if mod_id:
            embed.add_field(name="Mod ID", value=f"`{mod_id}`", inline=True)

    # Duration/Expiry (for mutes/timeouts)
    if action_type in ("mute", "timeout") and status == "open":
        if expires_at:
            embed.add_field(name="Expires", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True)
        else:
            duration_secs = case.get("duration_seconds")
            if duration_secs:
                # Permanent check (very long duration)
                if duration_secs >= 365 * 24 * 60 * 60:  # 1 year or more = permanent
                    embed.add_field(name="Duration", value="`Permanent`", inline=True)
                else:
                    from .utils import format_duration_precise
                    dur_str = format_duration_precise(duration_secs)
                    embed.add_field(name="Duration", value=f"`{dur_str}`", inline=True)

    # Created at
    created_at = case.get("created_at")
    if created_at:
        embed.add_field(name="Created", value=f"<t:{int(created_at)}:R>", inline=True)

    # Reason (if any)
    reason = case.get("reason")
    if reason:
        # Truncate long reasons
        if len(reason) > 200:
            reason = reason[:197] + "..."
        embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

    embed.set_footer(text="Use the buttons below to manage this case")

    return embed


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "build_mute_embed",
    "build_timeout_embed",
    "build_warn_embed",
    "build_unmute_embed",
    "build_expired_embed",
    "build_ban_embed",
    "build_unban_embed",
    "build_forbid_embed",
    "build_unforbid_embed",
    "build_profile_embed",
    "build_mute_evasion_embed",
    "build_vc_violation_embed",
    "build_member_left_embed",
    "build_control_panel_embed",
]
