"""
AzabBot - DM Helper Utilities
=============================

Centralized utilities for sending DMs to users with proper error handling.
Eliminates duplicate DM sending code across command files.

Usage:
    from src.utils.dm_helpers import safe_send_dm, build_moderation_dm

    # Simple DM
    success = await safe_send_dm(user, embed=my_embed)

    # DM with view (e.g., appeal button)
    success = await safe_send_dm(user, embed=my_embed, view=appeal_view)

    # Build a standard moderation DM
    embed = build_moderation_dm(
        title="You have been muted",
        color=EmbedColors.ERROR,
        guild=interaction.guild,
        moderator=interaction.user,
        reason=reason,
        fields=[("Duration", "1 hour")],
    )

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from typing import Optional, List, Tuple, Union

from src.core.logger import logger
from src.core.config import EmbedColors
from src.utils.footer import set_footer
from src.utils.discord_rate_limit import log_http_error


async def safe_send_dm(
    user: Union[discord.User, discord.Member],
    embed: Optional[discord.Embed] = None,
    content: Optional[str] = None,
    view: Optional[discord.ui.View] = None,
    context: Optional[str] = None,
) -> bool:
    """
    Safely send a DM to a user with proper error handling.

    Args:
        user: The user to send the DM to.
        embed: Optional embed to send.
        content: Optional text content to send.
        view: Optional view (buttons) to attach.
        context: Optional context string for logging (e.g., "Mute DM").

    Returns:
        True if DM was sent successfully, False otherwise.

    Example:
        success = await safe_send_dm(
            user=member,
            embed=my_embed,
            view=appeal_button_view,
            context="Ban Appeal DM",
        )
    """
    try:
        await user.send(content=content, embed=embed, view=view)
        return True
    except discord.Forbidden:
        # User has DMs disabled - this is expected and not an error
        if context:
            logger.debug("DM Blocked", [("Context", context), ("User", str(user))])
        return False
    except discord.HTTPException as e:
        # Network/API error - use shared rate limit logger
        log_http_error(e, "DM Send", [("User", str(user)), ("Context", context or "N/A")])
        return False


def build_moderation_dm(
    title: str,
    color: int,
    guild: discord.Guild,
    moderator: Optional[discord.Member] = None,
    reason: Optional[str] = None,
    evidence: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    description: Optional[str] = None,
) -> discord.Embed:
    """
    Build a standard moderation DM embed.

    Args:
        title: Embed title (e.g., "You have been muted").
        color: Embed color (use EmbedColors constants).
        guild: The guild where the action occurred.
        moderator: The moderator who performed the action (optional).
        reason: The reason for the action (optional).
        evidence: Evidence URL/text (optional).
        thumbnail_url: URL for thumbnail image (optional).
        fields: Additional fields as list of (name, value, inline) tuples.
        description: Optional description text.

    Returns:
        A discord.Embed ready to send.

    Example:
        embed = build_moderation_dm(
            title="You have been muted",
            color=EmbedColors.ERROR,
            guild=interaction.guild,
            moderator=interaction.user,
            reason="Spamming",
            fields=[
                ("Duration", "`1 hour`", True),
                ("Warning #", "`3`", True),
            ],
        )
    """
    embed = discord.Embed(title=title, color=color, description=description)

    # Standard fields
    embed.add_field(name="Server", value=f"`{guild.name}`", inline=False)

    # Add custom fields before moderator/reason
    if fields:
        for field in fields:
            if len(field) == 3:
                name, value, inline = field
            else:
                name, value = field
                inline = True
            embed.add_field(name=name, value=value, inline=inline)

    # Moderator (if provided)
    if moderator:
        embed.add_field(
            name="Moderator",
            value=f"`{moderator.display_name}`",
            inline=True,
        )

    # Reason
    if reason is not None:
        embed.add_field(
            name="Reason",
            value=f"`{reason}`" if reason else "`No reason provided`",
            inline=False,
        )

    # Evidence (only shown in DMs, not public)
    if evidence:
        embed.add_field(name="Evidence", value=evidence, inline=False)

    # Thumbnail
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    # Standard footer
    set_footer(embed)

    return embed


def build_appeal_dm(
    action_type: str,
    case_id: str,
    guild: discord.Guild,
) -> discord.Embed:
    """
    Build an appeal information embed to send after a moderation DM.

    Args:
        action_type: Type of action (e.g., "Ban", "Mute").
        case_id: The case ID for the action.
        guild: The guild where the action occurred.

    Returns:
        A discord.Embed with appeal information.
    """
    embed = discord.Embed(
        title=f"📝 Appeal Your {action_type}",
        description=f"If you believe this {action_type.lower()} was issued in error, you may submit an appeal.",
        color=EmbedColors.INFO,
    )
    embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
    embed.add_field(name="Server", value=f"`{guild.name}`", inline=True)
    set_footer(embed)

    return embed


async def send_moderation_dm(
    user: Union[discord.User, discord.Member],
    title: str,
    color: int,
    guild: discord.Guild,
    moderator: Optional[discord.Member] = None,
    reason: Optional[str] = None,
    evidence: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    description: Optional[str] = None,
    view: Optional[discord.ui.View] = None,
    context: Optional[str] = None,
) -> bool:
    """
    Build and send a moderation DM in one call.

    Convenience function that combines build_moderation_dm and safe_send_dm.

    Args:
        user: The user to DM.
        title: Embed title.
        color: Embed color.
        guild: The guild where action occurred.
        moderator: The moderator who performed the action.
        reason: The reason for the action.
        evidence: Evidence URL/text.
        thumbnail_url: URL for thumbnail.
        fields: Additional fields as (name, value, inline) tuples.
        description: Optional description.
        view: Optional view with buttons.
        context: Context for logging.

    Returns:
        True if DM was sent successfully, False otherwise.
    """
    embed = build_moderation_dm(
        title=title,
        color=color,
        guild=guild,
        moderator=moderator,
        reason=reason,
        evidence=evidence,
        thumbnail_url=thumbnail_url,
        fields=fields,
        description=description,
    )

    return await safe_send_dm(
        user=user,
        embed=embed,
        view=view,
        context=context,
    )


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "safe_send_dm",
    "build_moderation_dm",
    "build_appeal_dm",
    "send_moderation_dm",
]
