"""
AzabBot - Forbid Constants
==========================

Constants and configuration for the forbid command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Restriction types and their corresponding Discord permissions
RESTRICTIONS = {
    "reactions": {
        "permission": "add_reactions",
        "display": "Add Reactions",
        "emoji": "🚫",
        "description": "Cannot add reactions to messages",
    },
    "attachments": {
        "permission": "attach_files",
        "display": "Send Attachments",
        "emoji": "📎",
        "description": "Cannot send files or images",
    },
    "voice": {
        "permission": "connect",
        "display": "Join Voice",
        "emoji": "🔇",
        "description": "Cannot join voice channels",
    },
    "streaming": {
        "permission": "stream",
        "display": "Stream/Screenshare",
        "emoji": "📺",
        "description": "Cannot stream or screenshare in voice",
    },
    "embeds": {
        "permission": "embed_links",
        "display": "Embed Links",
        "emoji": "🔗",
        "description": "Cannot send embeds or link previews",
    },
    "threads": {
        "permissions": ["create_public_threads", "create_private_threads"],
        "display": "Create Threads",
        "emoji": "🧵",
        "description": "Cannot create threads",
    },
    "external_emojis": {
        "permission": "use_external_emojis",
        "display": "External Emojis",
        "emoji": "😀",
        "description": "Cannot use emojis from other servers",
    },
    "stickers": {
        "permission": "use_external_stickers",
        "display": "External Stickers",
        "emoji": "🎨",
        "description": "Cannot use stickers from other servers",
    },
}

# Role name prefix for forbid roles
FORBID_ROLE_PREFIX = "Forbid: "


__all__ = [
    "RESTRICTIONS",
    "FORBID_ROLE_PREFIX",
]
