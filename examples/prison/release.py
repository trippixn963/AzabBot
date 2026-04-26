"""
AzabBot - Prison Release Announcements
======================================

Release type constants and announcement functions.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, NY_TZ, EmbedColors
from src.utils.mention_resolver import embed_mention
from src.utils.action_gifs import fetch_action_gif

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Release Type Constants
# =============================================================================

class ReleaseType:
    """Constants for release announcement types."""
    TIME_SERVED = "time_served"
    MANUAL_UNMUTE = "manual_unmute"
    BOOSTER_CARD = "booster_card"
    COIN_UNJAIL = "coin_unjail"


# Release type display configuration
RELEASE_CONFIG = {
    ReleaseType.TIME_SERVED: {
        "title": "🔓 Released from Prison",
        "description": "{user} has served their time and is now free.",
        "color": EmbedColors.SUCCESS,
        "footer": None,
    },
    ReleaseType.MANUAL_UNMUTE: {
        "title": "🔓 Released from Prison",
        "description": "{user} has been released by {moderator}.",
        "color": EmbedColors.SUCCESS,
        "footer": None,
    },
    ReleaseType.BOOSTER_CARD: {
        "title": "<:unlock:1455200891866190040> Booster Unjail",
        "description": "{user} used their **daily Unjail Card** to escape prison!",
        "color": EmbedColors.BOOST_PINK,
        "footer": None,
    },
    ReleaseType.COIN_UNJAIL: {
        "title": "<:coins:1471898816671256677> Bought Freedom",
        "description": "{user} paid **{cost:,}** coins to buy their way out of prison!",
        "color": EmbedColors.GOLD,
        "footer": None,
    },
}


# =============================================================================
# Release Announcement Function
# =============================================================================

async def send_release_announcement(
    bot: "AzabBot",
    member: discord.Member,
    release_type: str,
    cost: Optional[int] = None,
    moderator: Optional[discord.Member] = None,
    time_served: Optional[str] = None) -> bool:
    """
    Send a release announcement to the general chat.

    Args:
        bot: Bot instance.
        member: Released member.
        release_type: Type of release (from ReleaseType constants).
        cost: Coin cost (for coin_unjail type).
        moderator: Moderator who released (for manual_unmute type).
        time_served: How long they were muted.

    Returns:
        True if announcement was sent successfully.
    """
    config = get_config()

    if not config.general_channel_id:
        logger.debug("Release Announcement Skipped", [
            ("User", f"{member.name} ({member.id})"),
            ("Reason", "No general channel configured"),
        ])
        return False

    channel = bot.get_channel(config.general_channel_id)
    if not channel:
        logger.warning("Release Announcement Failed", [
            ("User", f"{member.name} ({member.id})"),
            ("Reason", "General channel not found"),
            ("Channel ID", str(config.general_channel_id)),
        ])
        return False

    # Get release config
    release_info = RELEASE_CONFIG.get(release_type, RELEASE_CONFIG[ReleaseType.TIME_SERVED])

    # Build description with cost/moderator if applicable
    fmt = {"user": embed_mention(member)}
    if release_type == ReleaseType.COIN_UNJAIL and cost:
        fmt["cost"] = cost
    if release_type == ReleaseType.MANUAL_UNMUTE and moderator:
        fmt["moderator"] = moderator.mention
    else:
        fmt["moderator"] = "a moderator"
    description = release_info["description"].format(**fmt)

    # Create embed
    embed = discord.Embed(
        title=release_info["title"],
        description=description,
        color=release_info["color"]
    )

    # Set user avatar as thumbnail
    embed.set_thumbnail(url=member.display_avatar.url)

    # Add footer with feature advertisement
    embed.set_footer(text=release_info["footer"])

    # Fetch unmute GIF
    gif_url = await fetch_action_gif("unmute")
    if gif_url:
        embed.set_image(url=gif_url)

    try:
        await channel.send(embed=embed)

        logger.tree("Release Announcement Sent", [
            ("User", f"{member.name} ({member.id})"),
            ("Type", release_type),
            ("Channel", f"#{channel.name}"),
            ("Cost", f"{cost:,}" if cost else "N/A"),
        ], emoji="📢")

        return True

    except discord.Forbidden:
        logger.error("Release Announcement Failed (Permissions)", [
            ("User", f"{member.name} ({member.id})"),
            ("Channel", f"#{channel.name}"),
        ])
        return False
    except discord.HTTPException as e:
        logger.error("Release Announcement Failed (HTTP)", [
            ("User", f"{member.name} ({member.id})"),
            ("Error", str(e)[:50]),
        ])
        return False
    except Exception as e:
        logger.error("Release Announcement Failed", [
            ("User", f"{member.name} ({member.id})"),
            ("Error", str(e)[:50]),
        ])
        return False


__all__ = [
    "ReleaseType",
    "RELEASE_CONFIG",
    "send_release_announcement",
]
