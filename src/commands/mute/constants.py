"""
AzabBot - Mute Constants
========================

Constants and configuration for the mute command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Common duration options for autocomplete
DURATION_CHOICES = [
    ("10 minutes", "10m"),
    ("30 minutes", "30m"),
    ("1 hour", "1h"),
    ("6 hours", "6h"),
    ("12 hours", "12h"),
    ("1 day", "1d"),
    ("3 days", "3d"),
    ("7 days", "7d"),
    ("30 days", "30d"),
    ("Permanent", "permanent"),
]


__all__ = [
    "DURATION_CHOICES",
]
