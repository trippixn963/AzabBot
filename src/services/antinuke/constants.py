"""
AzabBot - Anti-Nuke Constants
=============================

Constants for anti-nuke protection thresholds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Thresholds for nuke detection (actions in time window)
BAN_THRESHOLD = 5
KICK_THRESHOLD = 5
CHANNEL_DELETE_THRESHOLD = 3
ROLE_DELETE_THRESHOLD = 3
BOT_ADD_THRESHOLD = 2  # Adding multiple bots quickly is suspicious
TIME_WINDOW = 60  # seconds

# Dangerous permissions that trigger immediate action
DANGEROUS_PERMISSIONS = {
    "administrator",
    "ban_members",
    "kick_members",
    "manage_guild",
    "manage_channels",
    "manage_roles",
    "manage_webhooks",
    "mention_everyone",
}

# Exempt users (owner is always exempt)
EXEMPT_ROLE_NAMES = ["Owner", "Admin", "Administrator"]


__all__ = [
    "BAN_THRESHOLD",
    "KICK_THRESHOLD",
    "CHANNEL_DELETE_THRESHOLD",
    "ROLE_DELETE_THRESHOLD",
    "BOT_ADD_THRESHOLD",
    "TIME_WINDOW",
    "DANGEROUS_PERMISSIONS",
    "EXEMPT_ROLE_NAMES",
]
