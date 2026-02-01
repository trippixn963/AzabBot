"""
AzabBot - Forbid Constants
==========================

Constants and configuration for the forbid command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# Restriction types and their corresponding Discord permissions
# Grouped by category: Text > Media > Emoji/Stickers > Threads > Voice
RESTRICTIONS = {
    # --- Text/Message Related ---
    "reactions": {
        "permission": "add_reactions",
        "display": "Add Reactions",
        "emoji": "👎",
        "description": "Cannot add reactions to messages",
    },
    "embeds": {
        "permission": "embed_links",
        "display": "Embed Links",
        "emoji": "🔗",
        "description": "Cannot send embeds or link previews",
    },
    # --- Media Related ---
    "attachments": {
        "permission": "attach_files",
        "display": "Attachments",
        "emoji": "📎",
        "description": "Cannot send files or images",
    },
    "voice_messages": {
        "permission": "send_voice_messages",
        "display": "Voice Messages",
        "emoji": "🎤",
        "description": "Cannot send voice messages/notes in chat",
    },
    "polls": {
        "permission": "send_polls",
        "display": "Polls",
        "emoji": "📊",
        "description": "Cannot create polls",
    },
    # --- Emoji/Stickers ---
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
    # --- Threads ---
    "threads": {
        "permissions": ["create_public_threads", "create_private_threads"],
        "display": "Create Threads",
        "emoji": "🧵",
        "description": "Cannot create threads",
    },
    # --- Voice Channel ---
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
}

# Role name prefix for forbid roles
FORBID_ROLE_PREFIX = "Forbid: "


__all__ = [
    "RESTRICTIONS",
    "FORBID_ROLE_PREFIX",
]
