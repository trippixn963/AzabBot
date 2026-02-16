"""
AzabBot - Jawdat Economy Constants
==================================

Cost tiers and configuration for coin-based features.

Unjail cost is calculated as: OFFENSE_TIER × DURATION_MULTIPLIER

Offense Tiers (based on weekly offense count):
- 1st offense: 45,000 coins base
- 2nd offense: 120,000 coins base
- 3rd offense: 240,000 coins base
- 4th+ offense: 450,000 coins base

Duration Multipliers:
- 1-3 hours: ×1.0
- 4-12 hours: ×2.0
- 12-24 hours: ×3.0
- 1-3 days: ×5.0
- 3-7 days: ×10.0
- 7+ days: ×20.0

Example costs:
- 1st offense, 2h mute: 45,000 × 1.0 = 45,000 coins
- 1st offense, 24h mute: 45,000 × 3.0 = 135,000 coins
- 4th offense, 24h mute: 450,000 × 3.0 = 1,350,000 coins
- 4th offense, 7d mute: 450,000 × 20.0 = 9,000,000 coins

Offense count resets every Sunday at midnight EST (same as XP drain).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Dict, Optional, Tuple


# =============================================================================
# Unjail Cost Tiers (Offense-based)
# =============================================================================

UNJAIL_OFFENSE_TIERS: Dict[int, int] = {
    1: 45_000,      # 1st offense: 45,000 coins base
    2: 120_000,     # 2nd offense: 120,000 coins base
    3: 240_000,     # 3rd offense: 240,000 coins base
    4: 450_000,     # 4th+ offense: 450,000 coins base
}

# =============================================================================
# Duration Multipliers (in hours)
# =============================================================================

# (max_hours, multiplier, tier_name) - sorted ascending
DURATION_MULTIPLIERS: list[tuple[int | None, float, str]] = [
    (3, 1.0, "1-3h"),       # 1-3 hours: ×1.0
    (12, 2.0, "4-12h"),     # 4-12 hours: ×2.0
    (24, 3.0, "12-24h"),    # 12-24 hours: ×3.0
    (72, 5.0, "1-3d"),      # 1-3 days: ×5.0
    (168, 10.0, "3-7d"),    # 3-7 days: ×10.0
    (None, 20.0, "7d+"),    # 7+ days: ×20.0
]

# Base cost shown on button (minimum possible cost)
UNJAIL_BASE_COST = 45_000

# Legacy export for backwards compatibility
UNJAIL_COST_TIERS = UNJAIL_OFFENSE_TIERS

# Custom emoji for coins
COINS_EMOJI_NAME = "coins"
COINS_EMOJI_ID = 1471898816671256677


# =============================================================================
# Helper Functions
# =============================================================================

def get_duration_multiplier(duration_hours: float) -> Tuple[float, str]:
    """
    Get the duration multiplier based on mute duration.

    Uses DURATION_MULTIPLIERS constant for consistency with documented tiers.

    Args:
        duration_hours: Mute duration in hours.

    Returns:
        Tuple of (multiplier, duration_tier_name).
    """
    for max_hours, multiplier, tier_name in DURATION_MULTIPLIERS:
        if max_hours is None or duration_hours <= max_hours:
            return multiplier, tier_name

    # Fallback (shouldn't reach here)
    return 20.0, "7d+"


def get_offense_base_cost(offense_count: int) -> int:
    """
    Get base unjail cost based on weekly offense count.

    Args:
        offense_count: Number of mutes this week (since Sunday midnight EST).

    Returns:
        Base coin cost before duration multiplier.
    """
    if offense_count <= 0:
        return UNJAIL_OFFENSE_TIERS[1]
    if offense_count >= 4:
        return UNJAIL_OFFENSE_TIERS[4]
    return UNJAIL_OFFENSE_TIERS.get(offense_count, UNJAIL_OFFENSE_TIERS[1])


def calculate_unjail_cost(offense_count: int, duration_hours: float) -> Tuple[int, dict]:
    """
    Calculate total unjail cost based on offense count and mute duration.

    Formula: OFFENSE_BASE × DURATION_MULTIPLIER

    Args:
        offense_count: Number of mutes this week.
        duration_hours: Mute duration in hours.

    Returns:
        Tuple of (total_cost, breakdown_dict).
    """
    base_cost = get_offense_base_cost(offense_count)
    multiplier, duration_tier = get_duration_multiplier(duration_hours)

    total_cost = int(base_cost * multiplier)

    breakdown = {
        "offense_count": offense_count,
        "base_cost": base_cost,
        "duration_hours": duration_hours,
        "duration_tier": duration_tier,
        "multiplier": multiplier,
        "total_cost": total_cost,
    }

    return total_cost, breakdown


def get_unjail_cost_for_user(user_id: int, guild_id: int) -> Tuple[int, int, Optional[dict]]:
    """
    Get unjail cost for a specific user based on their weekly offenses and mute duration.

    Args:
        user_id: Discord user ID.
        guild_id: Guild ID.

    Returns:
        Tuple of (cost, offense_count, breakdown_dict or None).
    """
    from src.core.database import get_db
    from src.core.logger import logger
    from datetime import datetime, timezone

    try:
        db = get_db()

        # Get weekly mute count (includes current mute)
        offense_count = db.get_user_mute_count_week(user_id, guild_id)

        # Minimum 1 offense (current mute)
        if offense_count < 1:
            offense_count = 1

        # Get active mute to determine duration
        mute_record = db.get_active_mute(user_id, guild_id)

        # Convert sqlite3.Row to dict if needed
        if mute_record and hasattr(mute_record, 'keys'):
            mute_record = dict(mute_record)

        if mute_record and mute_record.get("expires_at"):
            # Calculate total mute duration in hours
            muted_at = mute_record.get("muted_at")
            expires_at = mute_record.get("expires_at")

            if muted_at and expires_at:
                # Parse timestamps - could be float (unix), string (ISO), or datetime
                if isinstance(muted_at, (int, float)):
                    muted_at = datetime.fromtimestamp(muted_at, tz=timezone.utc)
                elif isinstance(muted_at, str):
                    muted_at = datetime.fromisoformat(muted_at.replace("Z", "+00:00"))

                if isinstance(expires_at, (int, float)):
                    expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc)
                elif isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

                duration_seconds = (expires_at - muted_at).total_seconds()
                duration_hours = max(1.0, duration_seconds / 3600)  # Minimum 1 hour
            else:
                duration_hours = 1.0  # Default to 1 hour if timestamps missing
        else:
            # Permanent mute or no expiry - treat as 7+ days
            duration_hours = 168.0

        cost, breakdown = calculate_unjail_cost(offense_count, duration_hours)

        logger.tree("Unjail Cost Calculated", [
            ("User ID", str(user_id)),
            ("Offense #", str(offense_count)),
            ("Duration", f"{duration_hours:.1f}h ({breakdown['duration_tier']})"),
            ("Base Cost", f"{breakdown['base_cost']:,}"),
            ("Multiplier", f"×{breakdown['multiplier']}"),
            ("Total Cost", f"{cost:,}"),
        ], emoji="🧮")

        return cost, offense_count, breakdown

    except Exception as e:
        logger.error("Failed to get unjail cost", [
            ("User ID", str(user_id)),
            ("Guild ID", str(guild_id)),
            ("Error", str(e)[:100]),
        ])
        # Return default (1st offense, short duration) on error
        return UNJAIL_OFFENSE_TIERS[1], 1, None


# Legacy function for backwards compatibility
def get_unjail_cost(offense_count: int) -> int:
    """Legacy function - use calculate_unjail_cost instead."""
    return get_offense_base_cost(offense_count)
