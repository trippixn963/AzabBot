"""
AzabBot - XP Drain Service
==========================

Drains XP from users when they get muted.
Integrates with SyriaBot's XP system via API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Dict, Any, Optional

import discord

from src.core.logger import logger
from src.core.config import get_config
from src.utils.http import http_session, FAST_TIMEOUT


# =============================================================================
# Constants
# =============================================================================

# XP drain tiers based on offense count
XP_DRAIN_TIERS: Dict[int, int] = {
    1: 500,      # 1st offense: -500 XP
    2: 1000,     # 2nd offense: -1,000 XP
    3: 2500,     # 3rd offense: -2,500 XP
    4: 5000,     # 4th+ offense: -5,000 XP
}


# =============================================================================
# Helper Functions
# =============================================================================

def get_drain_amount(offense_count: int) -> int:
    """
    Get XP drain amount based on offense count.

    Args:
        offense_count: Number of mutes the user has received.

    Returns:
        XP amount to drain.
    """
    if offense_count >= 4:
        return XP_DRAIN_TIERS[4]
    return XP_DRAIN_TIERS.get(offense_count, XP_DRAIN_TIERS[1])


def is_drain_exempt(member: discord.Member) -> bool:
    """
    Check if a member is exempt from XP drain.

    Currently exempt:
    - Server boosters

    Args:
        member: Discord member to check.

    Returns:
        True if exempt from XP drain.
    """
    # Server boosters are exempt
    if member.premium_since is not None:
        return True

    return False


# =============================================================================
# API Functions
# =============================================================================

async def drain_user_xp(
    user_id: int,
    offense_count: int,
    reason: str = "Mute penalty",
) -> Optional[Dict[str, Any]]:
    """
    Drain XP from a user via SyriaBot API.

    Uses shared HTTP session with connection pooling and retry logic.

    Args:
        user_id: Discord user ID.
        offense_count: Number of mutes (determines drain amount).
        reason: Reason for the drain (for logging).

    Returns:
        API response dict on success, None on failure.
    """
    config = get_config()
    api_key = config.SYRIA_XP_API_KEY
    if not api_key:
        logger.debug("XP Drain Skipped", [("Reason", "No API key configured")])
        return None

    drain_amount = get_drain_amount(offense_count)
    api_url = f"http://localhost:{config.SYRIA_API_PORT}/api/syria/xp/drain"

    # Use shared session with retry logic
    response = await http_session.post_with_retry(
        api_url,
        json={
            "user_id": user_id,
            "amount": drain_amount,
            "reason": f"{reason} (Offense #{offense_count})",
        },
        headers={"X-API-Key": api_key},
        timeout=FAST_TIMEOUT,
    )

    if response is None:
        # post_with_retry already logged the failure
        return None

    try:
        if response.status == 200:
            data = await response.json()
            old_xp = data.get("old_xp")
            new_xp = data.get("new_xp")
            xp_display = f"{old_xp:,} → {new_xp:,}" if old_xp is not None and new_xp is not None else "?"
            logger.tree("XP Drained", [
                ("User ID", str(user_id)),
                ("Offense #", str(offense_count)),
                ("Amount", f"-{drain_amount:,}"),
                ("XP", xp_display),
                ("Level Drop", "Yes" if data.get("level_dropped") else "No"),
            ], emoji="⬇️")
            return data

        # Consume response body to release connection
        body = await response.text()

        if response.status == 404:
            logger.debug("XP Drain Skipped", [
                ("User ID", str(user_id)),
                ("Reason", "User not in XP system"),
            ])
            return None

        logger.warning("XP Drain API Error", [
            ("User ID", str(user_id)),
            ("Status", str(response.status)),
            ("Response", body[:100]),
        ])
        return None

    except Exception as e:
        logger.error("XP Drain Response Error", [
            ("User ID", str(user_id)),
            ("Error", str(e)[:100]),
        ])
        return None


# =============================================================================
# Main Entry Point
# =============================================================================

async def process_mute_xp_drain(
    member: discord.Member,
    guild_id: int,
    offense_count: int,
    is_extension: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Process XP drain for a mute action.

    Handles all checks (extension, exemptions) before draining.
    This is the main entry point called from mute_ops.py.
    Also records the drain amount to the database for stats tracking.

    Args:
        member: Discord member who was muted.
        guild_id: Guild ID where mute occurred.
        offense_count: User's total mute count.
        is_extension: Whether this is a mute extension.

    Returns:
        API response dict on success, None if skipped/failed.
    """
    from src.core.database import get_db

    # Skip for mute extensions (no double penalty)
    if is_extension:
        logger.debug("XP Drain Skipped", [
            ("User", f"{member.name} ({member.id})"),
            ("Reason", "Mute extension"),
        ])
        return None

    # Check exemptions
    if is_drain_exempt(member):
        logger.debug("XP Drain Exempt", [
            ("User", f"{member.name} ({member.id})"),
            ("Reason", "Server Booster"),
        ])
        return None

    # Log intent before API call
    drain_amount = get_drain_amount(offense_count)
    logger.debug("XP Drain Processing", [
        ("User", f"{member.name} ({member.id})"),
        ("Offense #", str(offense_count)),
        ("Amount", f"-{drain_amount:,}"),
    ])

    # Execute drain
    result = await drain_user_xp(
        user_id=member.id,
        offense_count=offense_count,
        reason="Muted in server",
    )

    # Record drain amount to database if successful
    if result is not None:
        try:
            db = get_db()
            db.update_mute_xp_drained(member.id, guild_id, drain_amount)
        except Exception as e:
            logger.error("XP Drain DB Update Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Amount", f"{drain_amount:,}"),
                ("Error", str(e)[:100]),
            ])

    return result


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Constants
    "XP_DRAIN_TIERS",
    # Functions
    "get_drain_amount",
    "is_drain_exempt",
    "drain_user_xp",
    "process_mute_xp_drain",
]
