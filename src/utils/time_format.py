"""
Azab Discord Bot - Time Formatting Utils
========================================

Time formatting utilities for human-readable duration display.
Converts minutes into user-friendly duration strings for embeds and messages.

Features:
- Convert minutes to days, hours, minutes format
- Human-readable duration strings (e.g., "2d 3h 15m")
- Handle zero and negative values gracefully
- Compact format for Discord embeds

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""


def format_duration(total_minutes: int) -> str:
    """
    Format minutes into a human-readable duration string.

    Converts a duration in minutes to a compact human-readable format
    suitable for Discord embeds and messages. Handles edge cases like
    zero or negative durations gracefully.

    Args:
        total_minutes: Total number of minutes to format

    Returns:
        Formatted string in format "XdYhZm" where:
        - X = days (omitted if 0)
        - Y = hours (omitted if 0)
        - Z = minutes (always shown if days and hours are 0)

        Examples:
        - 45 minutes: "45m"
        - 125 minutes: "2h 5m"
        - 1500 minutes: "1d 1h"
        - 0 minutes: "0m"
    """
    # DESIGN: Handle invalid or zero durations gracefully
    # Negative durations shouldn't occur but protect against data corruption
    # Empty string or zero returns "0m" for user-friendly display
    if not total_minutes or total_minutes < 0:
        return "0m"

    # DESIGN: Calculate days, hours, minutes using integer division
    # // operator gives whole number of days/hours, % gives remainder
    # 1 day = 24 * 60 = 1440 minutes constant for clarity
    days: int = total_minutes // (24 * 60)
    remaining: int = total_minutes % (24 * 60)
    hours: int = remaining // 60
    minutes: int = remaining % 60

    # DESIGN: Build duration string with only non-zero components
    # Omits days if 0, omits hours if 0 for compact display
    # Always shows minutes as fallback (prevents empty string)
    parts: list[str] = []

    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    # Always show minutes if it's the only component (to avoid empty strings)
    if minutes > 0 or (days == 0 and hours == 0):
        parts.append(f"{minutes}m")

    # DESIGN: Join with spaces for readability in Discord embeds
    # "1d 2h 30m" is easier to read than "1d2h30m"
    return " ".join(parts)
