"""
AzabBot - Duration Utilities
============================

Centralized utilities for parsing and formatting durations.
Consolidates duplicate duration functions across the codebase.

Usage:
    from src.utils.duration import parse_duration, format_duration

    # Parse "1d12h30m" to seconds
    seconds = parse_duration("1d12h30m")  # 131400

    # Format seconds to human-readable
    display = format_duration(131400)  # "1d 12h 30m"

    # Permanent durations
    seconds = parse_duration("permanent")  # None
    display = format_duration(None)  # "Permanent"

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import Optional


# =============================================================================
# Time Constants
# =============================================================================

SECONDS_PER_YEAR = 31536000
SECONDS_PER_WEEK = 604800
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60

PERMANENT_KEYWORDS = frozenset({"permanent", "perm", "forever", "indefinite"})

TIME_MULTIPLIERS = {
    "y": SECONDS_PER_YEAR,
    "w": SECONDS_PER_WEEK,
    "d": SECONDS_PER_DAY,
    "h": SECONDS_PER_HOUR,
    "m": SECONDS_PER_MINUTE,
    "s": 1,
}


# =============================================================================
# Parsing Functions
# =============================================================================

def parse_duration(duration_str: str) -> Optional[int]:
    """
    Parse a duration string into seconds.

    Supports multiple formats:
        - "10m", "30m" for minutes
        - "1h", "6h" for hours
        - "1d", "7d" for days
        - "1w" for weeks
        - "1y" for years
        - Combined: "1d12h30m", "2w3d"
        - "permanent", "perm", "forever" for None (no expiry)
        - Plain number: "30" → 30 minutes

    Args:
        duration_str: Duration string to parse.

    Returns:
        Duration in seconds, or None for permanent/invalid.

    Examples:
        >>> parse_duration("1h")
        3600
        >>> parse_duration("1d12h")
        129600
        >>> parse_duration("permanent")
        None
        >>> parse_duration("30")
        1800
    """
    if not duration_str:
        return None

    duration_str = duration_str.lower().strip()

    # Check for permanent durations
    if duration_str in PERMANENT_KEYWORDS:
        return None

    # Try combined format like "1y2w3d12h30m"
    pattern = r"(?:(\d+)y)?(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
    match = re.fullmatch(pattern, duration_str)

    if match and any(match.groups()):
        years = int(match.group(1) or 0)
        weeks = int(match.group(2) or 0)
        days = int(match.group(3) or 0)
        hours = int(match.group(4) or 0)
        minutes = int(match.group(5) or 0)
        seconds = int(match.group(6) or 0)

        total = (
            years * SECONDS_PER_YEAR +
            weeks * SECONDS_PER_WEEK +
            days * SECONDS_PER_DAY +
            hours * SECONDS_PER_HOUR +
            minutes * SECONDS_PER_MINUTE +
            seconds
        )
        return total if total > 0 else None

    # Try single unit format (e.g., "30m", "2h", "1d")
    single_match = re.match(r"^(\d+)\s*([ywdhms])?$", duration_str)
    if single_match:
        value = int(single_match.group(1))
        unit = single_match.group(2) or "m"  # Default to minutes
        return value * TIME_MULTIPLIERS.get(unit, SECONDS_PER_MINUTE)

    return None


# =============================================================================
# Formatting Functions
# =============================================================================

def format_duration(
    seconds: Optional[int],
    max_units: int = 3,
    show_seconds: bool = False,
) -> str:
    """
    Format seconds into a human-readable duration string.

    Args:
        seconds: Duration in seconds, or None for permanent.
        max_units: Maximum number of time units to show (default 3).
        show_seconds: Whether to show seconds in output (default False).

    Returns:
        Formatted string like "1d 12h 30m" or "Permanent".

    Examples:
        >>> format_duration(None)
        "Permanent"
        >>> format_duration(3661)
        "1h 1m"
        >>> format_duration(90061)
        "1d 1h 1m"
        >>> format_duration(45)
        "< 1m"
        >>> format_duration(45, show_seconds=True)
        "45s"
    """
    if seconds is None:
        return "Permanent"

    if seconds <= 0:
        return "0m" if not show_seconds else "0s"

    if seconds < SECONDS_PER_MINUTE and not show_seconds:
        return "< 1m"

    parts = []

    # Years
    if seconds >= SECONDS_PER_YEAR:
        years, seconds = divmod(seconds, SECONDS_PER_YEAR)
        parts.append(f"{years}y")

    # Weeks
    if seconds >= SECONDS_PER_WEEK and len(parts) < max_units:
        weeks, seconds = divmod(seconds, SECONDS_PER_WEEK)
        parts.append(f"{weeks}w")

    # Days
    if seconds >= SECONDS_PER_DAY and len(parts) < max_units:
        days, seconds = divmod(seconds, SECONDS_PER_DAY)
        parts.append(f"{days}d")

    # Hours
    if seconds >= SECONDS_PER_HOUR and len(parts) < max_units:
        hours, seconds = divmod(seconds, SECONDS_PER_HOUR)
        parts.append(f"{hours}h")

    # Minutes
    if seconds >= SECONDS_PER_MINUTE and len(parts) < max_units:
        minutes, seconds = divmod(seconds, SECONDS_PER_MINUTE)
        parts.append(f"{minutes}m")

    # Seconds
    if show_seconds and seconds > 0 and len(parts) < max_units:
        parts.append(f"{seconds}s")

    return " ".join(parts) if parts else ("0s" if show_seconds else "< 1m")


def format_duration_short(seconds: Optional[int]) -> str:
    """
    Format seconds into a short duration string (max 2 units).

    Convenience wrapper for format_duration with max_units=2.

    Args:
        seconds: Duration in seconds, or None for permanent.

    Returns:
        Formatted string like "1d 12h" or "Permanent".

    Examples:
        >>> format_duration_short(90061)
        "1d 1h"
    """
    return format_duration(seconds, max_units=2)


def format_duration_from_minutes(minutes: int) -> str:
    """
    Format minutes into a human-readable duration string.

    Provided for compatibility with code that works in minutes.

    Args:
        minutes: Duration in minutes.

    Returns:
        Formatted string like "2d 5h 30m".

    Examples:
        >>> format_duration_from_minutes(90)
        "1h 30m"
    """
    if not minutes:
        return "0m"
    return format_duration(minutes * SECONDS_PER_MINUTE)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Constants
    "SECONDS_PER_YEAR",
    "SECONDS_PER_WEEK",
    "SECONDS_PER_DAY",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_MINUTE",
    "PERMANENT_KEYWORDS",
    # Parsing
    "parse_duration",
    # Formatting
    "format_duration",
    "format_duration_short",
    "format_duration_from_minutes",
]
