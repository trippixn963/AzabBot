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
        "description": "{user} has been released by a moderator.",
        "color": EmbedColors.SUCCESS,
        "footer": None,
    },
    ReleaseType.BOOSTER_CARD: {
        "title": "<:unlock:1455200891866190040> Booster Unjail",
        "description": "{user} used their **daily Unjail Card** to escape prison!",
        "color": 0xF47FFF,  # Boost pink
        "footer": None,
    },
    ReleaseType.COIN_UNJAIL: {
        "title": "<:coins:1471898816671256677> Bought Freedom",
        "description": "{user} paid **{cost:,}** coins to buy their way out of prison!",
        "color": 0xFFD700,  # Gold
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

    # Build description with cost if applicable
    if release_type == ReleaseType.COIN_UNJAIL and cost:
        description = release_info["description"].format(user=member.mention, cost=cost)
    else:
        description = release_info["description"].format(user=member.mention)

    # Create embed
    embed = discord.Embed(
        title=release_info["title"],
        description=description,
        color=release_info["color"]
    )

    # Add time served if available
    if time_served:
        embed.add_field(name="Time Served", value=f"`{time_served}`", inline=True)

    # Add moderator if manual unmute
    if release_type == ReleaseType.MANUAL_UNMUTE and moderator:
        embed.add_field(name="Released By", value=moderator.mention, inline=True)

    # Add cost breakdown for coin unjail
    if release_type == ReleaseType.COIN_UNJAIL and cost:
        embed.add_field(name="Cost Paid", value=f"`{cost:,}` coins", inline=True)

    # Set user avatar as thumbnail
    embed.set_thumbnail(url=member.display_avatar.url)

    # Add footer with feature advertisement
    embed.set_footer(text=release_info["footer"])

    # Add promotional field for boosters/economy (only for time served releases)
    if release_type == ReleaseType.TIME_SERVED:
        promo_text = (
            "**<:unlock:1455200891866190040> Boosters** get a free daily Unjail Card\n"
            "**<:coins:1471898816671256677> Everyone** can buy their way out with Jawdat coins"
        )
        embed.add_field(name="Skip the Wait", value=promo_text, inline=False)

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
