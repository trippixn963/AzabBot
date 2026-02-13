"""
AzabBot - Prison Welcome Embed Builder
======================================

Builds the welcome embed for newly muted prisoners.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from typing import Optional, Dict, Any, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import EmbedColors
from src.utils.duration import format_duration_from_minutes as format_duration
from src.services.appeals.constants import MIN_APPEALABLE_MUTE_DURATION
from src.services.xp_drain import get_drain_amount, is_drain_exempt

if TYPE_CHECKING:
    from src.bot import AzabBot
    from sqlite3 import Row


def build_welcome_embed(
    member: discord.Member,
    mute_record: Optional["Row"],
    mute_reason: Optional[str],
    prisoner_stats: Dict[str, Any],
    offense_count_week: int,
    time_served_week: int,
) -> discord.Embed:
    """
    Build the welcome embed for a new prisoner.

    Args:
        member: The muted member.
        mute_record: Active mute record from database.
        mute_reason: Reason for the mute.
        prisoner_stats: Stats from get_prisoner_stats().
        offense_count_week: Number of mutes this week.
        time_served_week: Minutes served this week.

    Returns:
        Configured discord.Embed.
    """
    # Calculate sentence text
    sentence_text = None
    if mute_record and mute_record["expires_at"]:
        # Ensure both values are floats (database may store as string)
        expires_at = float(mute_record["expires_at"])
        muted_at = float(mute_record["muted_at"])
        duration_seconds = int(expires_at - muted_at)
        duration_minutes = duration_seconds // 60
        sentence_text = format_duration(duration_minutes)
    elif mute_record:
        sentence_text = "Permanent"

    # Create embed
    embed = discord.Embed(
        title="🔒 Arrived to Prison",
        color=EmbedColors.GOLD,
    )

    embed.add_field(name="Prisoner", value=member.mention, inline=True)

    if sentence_text:
        embed.add_field(name="Sentence", value=f"`{sentence_text}`", inline=True)

    # Add unmute time in Discord timestamp format (shows in user's timezone)
    if mute_record and mute_record["expires_at"]:
        unmute_ts = int(mute_record["expires_at"])
        embed.add_field(name="Unmutes", value=f"<t:{unmute_ts}:F> (<t:{unmute_ts}:R>)", inline=False)

    if mute_reason:
        # Truncate long reasons
        reason_display = mute_reason[:100] + "..." if len(mute_reason) > 100 else mute_reason
        embed.add_field(name="Reason", value=f"`{reason_display}`", inline=False)

    # Weekly stats
    if offense_count_week > 0:
        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(offense_count_week, f"{offense_count_week}th")
        embed.add_field(name="Offense #", value=f"`{ordinal}` this week", inline=True)

    if time_served_week > 0:
        time_display = format_duration(time_served_week)
        embed.add_field(name="Time Served", value=f"`{time_display}` this week", inline=True)

    # Add XP Lost field (if user is not exempt)
    if not is_drain_exempt(member) and offense_count_week > 0:
        xp_lost = get_drain_amount(offense_count_week)
        embed.add_field(name="XP Lost", value=f"`-{xp_lost:,}`", inline=True)

    # Add booster unjail card notice (only for mutes >= 1 hour or permanent)
    is_booster = member.premium_since is not None
    mute_qualifies_for_unjail = _check_mute_qualifies(mute_record)

    if is_booster and mute_qualifies_for_unjail:
        # Import here to avoid circular imports
        from src.core.database import get_db
        db = get_db()

        can_use_card = db.can_use_unjail_card(member.id, member.guild.id)
        if can_use_card:
            embed.add_field(
                name="<:unlock:1455200891866190040> Booster Perk",
                value="Your daily **Unjail Card** is available! Use the button below to release yourself.",
                inline=False,
            )
        else:
            reset_at = db.get_unjail_card_cooldown(member.id, member.guild.id)
            if reset_at:
                embed.add_field(
                    name="<:unlock:1455200891866190040> Booster Perk",
                    value=f"Unjail Card on cooldown. Resets <t:{int(reset_at)}:R>",
                    inline=False,
                )

    # Add coin unjail cost (for mutes >= 1 hour or permanent)
    if mute_qualifies_for_unjail:
        try:
            from src.services.jawdat_economy import get_unjail_cost_for_user, COINS_EMOJI_ID
            unjail_cost, _, _ = get_unjail_cost_for_user(member.id, member.guild.id)

            embed.add_field(
                name=f"<:coins:{COINS_EMOJI_ID}> Coin Unjail",
                value=f"**{unjail_cost:,}** coins",
                inline=False,
            )
        except Exception as e:
            logger.warning("Failed to add unjail cost field", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", str(e)[:50]),
            ])

    embed.set_thumbnail(
        url=member.avatar.url if member.avatar else member.default_avatar.url
    )

    return embed


def _check_mute_qualifies(mute_record: Optional["Row"]) -> bool:
    """Check if mute qualifies for unjail options (>= 1 hour or permanent)."""
    if not mute_record:
        return False

    is_permanent = mute_record["expires_at"] is None
    if is_permanent:
        return True

    if mute_record["expires_at"] and mute_record["muted_at"]:
        # Ensure both values are floats (database may store as string)
        expires_at = float(mute_record["expires_at"])
        muted_at = float(mute_record["muted_at"])
        duration_secs = int(expires_at - muted_at)
        return duration_secs >= MIN_APPEALABLE_MUTE_DURATION

    return False


__all__ = ["build_welcome_embed"]
