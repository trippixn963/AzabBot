"""
Unified Duration Utilities
==========================

Centralized utilities for parsing and formatting durations.
Supports both timedelta and seconds-based APIs for compatibility.

Usage:
    from src.utils.duration import parse_duration, format_duration

    # Parse duration to seconds
    seconds = parse_duration("1d12h30m")  # 131400

    # Parse duration to timedelta
    td = parse_duration_timedelta("1d")  # timedelta(days=1)

    # Format seconds to human-readable
    display = format_duration(131400)  # "1d 12h 30m"

    # Permanent durations
    seconds = parse_duration("permanent")  # None
    display = format_duration(None)  # "Permanent"

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import timedelta
from typing import Optional


# =============================================================================
# Time Constants
# =============================================================================

SECONDS_PER_YEAR = 31536000
SECONDS_PER_MONTH = 2592000  # 30 days
SECONDS_PER_WEEK = 604800
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60

PERMANENT_KEYWORDS = frozenset({"permanent", "perm", "forever", "indefinite", "inf"})

TIME_MULTIPLIERS = {
    "y": SECONDS_PER_YEAR,
    "mo": SECONDS_PER_MONTH,
    "w": SECONDS_PER_WEEK,
    "d": SECONDS_PER_DAY,
    "h": SECONDS_PER_HOUR,
    "m": SECONDS_PER_MINUTE,
    "s": 1,
}

# Full word aliases mapping to short forms
TIME_UNIT_ALIASES = {
    # Years
    "year": "y", "years": "y", "yr": "y", "yrs": "y",
    # Months
    "month": "mo", "months": "mo", "mon": "mo",
    # Weeks
    "week": "w", "weeks": "w", "wk": "w", "wks": "w",
    # Days
    "day": "d", "days": "d",
    # Hours
    "hour": "h", "hours": "h", "hr": "h", "hrs": "h",
    # Minutes
    "minute": "m", "minutes": "m", "min": "m", "mins": "m",
    # Seconds
    "second": "s", "seconds": "s", "sec": "s", "secs": "s",
}


# =============================================================================
# Duration Suggestions for Autocomplete
# =============================================================================

DURATION_SUGGESTIONS = [
    ("1 Hour", "1h"),
    ("6 Hours", "6h"),
    ("12 Hours", "12h"),
    ("1 Day", "1d"),
    ("3 Days", "3d"),
    ("1 Week", "1w"),
    ("2 Weeks", "2w"),
    ("1 Month", "1mo"),
    ("3 Months", "3mo"),
    ("Permanent", "permanent"),
]


# =============================================================================
# Parsing Functions
# =============================================================================

def _normalize_duration_string(duration_str: str) -> str:
    """
    Normalize duration string by converting full words to short forms.

    Uses word boundaries to avoid mangling unrelated words.

    Examples:
        "1 day" -> "1d"
        "1day" -> "1d"
        "2 hours" -> "2h"
        "1 week 2 days" -> "1w2d"
        "1 monday" -> "1 monday" (not mangled, will fail validation)
    """
    result = duration_str.lower().strip()

    # Remove extra spaces around numbers (but keep word separation)
    result = re.sub(r"(\d+)\s+", r"\1", result)

    # Replace full words with short forms using word boundaries
    # Sort by length (longest first) to avoid partial matches
    for word, short in sorted(TIME_UNIT_ALIASES.items(), key=lambda x: -len(x[0])):
        # Use word boundary \b to only match whole words
        # Also handle case where word is attached to a number (e.g., "1day")
        result = re.sub(rf"(?<=\d){word}\b|(?<!\w){word}\b", short, result)

    # Remove any remaining spaces
    result = result.replace(" ", "")

    return result


def parse_duration(duration_str: str) -> Optional[int]:
    """
    Parse a duration string into seconds.

    Supports multiple formats:
        - "10m", "30m" for minutes
        - "1h", "6h" for hours
        - "1d", "7d" for days
        - "1w" for weeks
        - "1mo", "3mo" for months
        - "1y" for years
        - Combined: "1d12h30m", "2w3d"
        - "permanent", "perm", "forever" for None (no expiry)
        - Plain number: "30" -> 30 minutes
        - Full words: "1 day", "2 hours", "1day", "3 weeks"

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
        >>> parse_duration("1 day")
        86400
        >>> parse_duration("2hours")
        7200
    """
    if not duration_str:
        return None

    duration_str = duration_str.lower().strip()

    # Check for permanent durations
    if duration_str in PERMANENT_KEYWORDS:
        return None

    # Normalize full words to short forms
    normalized = _normalize_duration_string(duration_str)

    # Try combined format like "1y2w3d12h30m" (with optional month support)
    pattern = r"(?:(\d+)y)?(?:(\d+)mo)?(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
    match = re.fullmatch(pattern, normalized)

    if match and any(match.groups()):
        years = int(match.group(1) or 0)
        months = int(match.group(2) or 0)
        weeks = int(match.group(3) or 0)
        days = int(match.group(4) or 0)
        hours = int(match.group(5) or 0)
        minutes = int(match.group(6) or 0)
        seconds = int(match.group(7) or 0)

        total = (
            years * SECONDS_PER_YEAR +
            months * SECONDS_PER_MONTH +
            weeks * SECONDS_PER_WEEK +
            days * SECONDS_PER_DAY +
            hours * SECONDS_PER_HOUR +
            minutes * SECONDS_PER_MINUTE +
            seconds
        )
        return total if total > 0 else None

    # Try single unit format (e.g., "30m", "2h", "1d", "1mo")
    single_match = re.match(r"^(\d+)\s*(y|mo|w|d|h|m|s)?$", normalized)
    if single_match:
        value = int(single_match.group(1))
        unit = single_match.group(2) or "m"  # Default to minutes
        return value * TIME_MULTIPLIERS.get(unit, SECONDS_PER_MINUTE)

    return None


def parse_duration_timedelta(duration_str: str) -> Optional[timedelta]:
    """
    Parse a duration string into a timedelta.

    This is a convenience wrapper around parse_duration() for code that
    prefers timedelta objects over raw seconds.

    Supports formats like:
    - 1m, 5m, 30m (minutes)
    - 1h, 6h, 12h, 24h (hours)
    - 1d, 3d, 7d (days)
    - 1w, 2w (weeks)
    - 1mo, 3mo, 6mo (months, approximated as 30 days)
    - permanent, perm, forever (returns None)

    Returns:
        timedelta if parsed successfully, None for permanent bans

    Raises:
        ValueError: If duration format is invalid
    """
    seconds = parse_duration(duration_str)
    if seconds is None:
        # Could be permanent or invalid - check which
        if duration_str and duration_str.lower().strip() in PERMANENT_KEYWORDS:
            return None
        if not duration_str:
            raise ValueError("Empty duration string")
        raise ValueError(f"Invalid duration format: {duration_str}")
    return timedelta(seconds=seconds)


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

    # Months
    if seconds >= SECONDS_PER_MONTH and len(parts) < max_units:
        months, seconds = divmod(seconds, SECONDS_PER_MONTH)
        parts.append(f"{months}mo")

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


def format_duration_timedelta(td: Optional[timedelta]) -> str:
    """
    Format a timedelta into a human-readable string.

    This is a convenience wrapper for code that works with timedelta objects.

    Args:
        td: timedelta to format, or None for permanent

    Returns:
        Human-readable duration string
    """
    if td is None:
        return "Permanent"

    total_seconds = int(td.total_seconds())

    if total_seconds < SECONDS_PER_HOUR:  # Less than 1 hour
        minutes = total_seconds // SECONDS_PER_MINUTE
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif total_seconds < SECONDS_PER_DAY:  # Less than 1 day
        hours = total_seconds // SECONDS_PER_HOUR
        return f"{hours} hour{'s' if hours != 1 else ''}"
    elif total_seconds < SECONDS_PER_WEEK:  # Less than 1 week
        days = total_seconds // SECONDS_PER_DAY
        return f"{days} day{'s' if days != 1 else ''}"
    elif total_seconds < SECONDS_PER_MONTH:  # Less than 30 days
        weeks = total_seconds // SECONDS_PER_WEEK
        return f"{weeks} week{'s' if weeks != 1 else ''}"
    else:
        months = total_seconds // SECONDS_PER_MONTH
        return f"{months} month{'s' if months != 1 else ''}"


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
    "SECONDS_PER_MONTH",
    "SECONDS_PER_WEEK",
    "SECONDS_PER_DAY",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_MINUTE",
    "PERMANENT_KEYWORDS",
    "DURATION_SUGGESTIONS",
    # Parsing (seconds-based)
    "parse_duration",
    # Parsing (timedelta-based)
    "parse_duration_timedelta",
    # Formatting (seconds-based)
    "format_duration",
    "format_duration_short",
    "format_duration_from_minutes",
    # Formatting (timedelta-based)
    "format_duration_timedelta",
]
