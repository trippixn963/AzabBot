"""
Azab Discord Bot - Time Formatting Utils
========================================

Time formatting utilities for the Azab Discord bot.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""


def format_duration(total_minutes: int) -> str:
    """
    Format minutes into a human-readable duration string.

    Args:
        total_minutes: Total number of minutes

    Returns:
        Formatted string like "2d 3h 15m" or "45m" or "3h 20m"
    """
    if not total_minutes or total_minutes < 0:
        return "0m"

    days = total_minutes // (24 * 60)
    remaining = total_minutes % (24 * 60)
    hours = remaining // 60
    minutes = remaining % 60

    parts = []

    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or (days == 0 and hours == 0):
        parts.append(f"{minutes}m")

    return " ".join(parts)