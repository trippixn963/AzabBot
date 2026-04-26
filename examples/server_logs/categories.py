"""
AzabBot - Categories
====================

Log category definitions for the server logging service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from enum import Enum


class LogCategory(Enum):
    """Log category enum mapping to thread names."""
    MOD_ACTIONS = "📋 Mod Actions"
    BANS_KICKS = "🔨 Bans & Kicks"
    MUTES_TIMEOUTS = "🔇 Mutes & Timeouts"
    MESSAGES = "📝 Message Logs"
    JOINS = "📥 Member Joins"
    LEAVES = "📤 Member Leaves"
    ROLE_CHANGES = "🏷️ Role Changes"
    NAME_CHANGES = "✨ Name Changes"
    AVATAR_CHANGES = "🖼️ Avatar Changes"
    VOICE = "🔊 Voice Activity"
    CHANNELS = "📁 Channel Changes"
    THREADS = "🧵 Thread Activity"
    ROLES = "🎭 Role Management"
    EMOJI_STICKERS = "😀 Emoji & Stickers"
    SERVER_SETTINGS = "⚙️ Server Settings"
    PERMISSIONS = "🔐 Permissions"
    BOTS_INTEGRATIONS = "🤖 Bots & Integrations"
    AUTOMOD = "🛡️ AutoMod Actions"
    EVENTS = "📅 Scheduled Events"
    REACTIONS = "💬 Reactions"
    STAGE = "🎤 Stage Activity"
    BOOSTS = "💎 Server Boosts"
    INVITES = "🔗 Invite Activity"
    ALERTS = "🚨 Security Alerts"
    ALLIANCES = "🤝 Alliances"
    TICKETS = "🎫 Tickets"
    TRANSCRIPTS = "📜 Transcripts"
    APPEALS = "📨 Appeals"
    WARNINGS = "⚠️ Warnings"


# Thread descriptions for each category
THREAD_DESCRIPTIONS = {
    LogCategory.MOD_ACTIONS: "Logs for mod command usage: snipe, history, purge, forbid, warn, etc.",
    LogCategory.BANS_KICKS: "Logs for bans, unbans, and kicks",
    LogCategory.MUTES_TIMEOUTS: "Logs for mutes, unmutes, timeouts, and timeout removals",
    LogCategory.MESSAGES: "Logs for message edits, deletes, and bulk deletes",
    LogCategory.JOINS: "Logs for new member joins with invite tracking",
    LogCategory.LEAVES: "Logs for member leaves with role info and duration",
    LogCategory.ROLE_CHANGES: "Logs for role additions and removals from users",
    LogCategory.NAME_CHANGES: "Logs for nickname and username changes",
    LogCategory.AVATAR_CHANGES: "Logs for profile picture changes",
    LogCategory.VOICE: "Logs for voice joins, leaves, moves, mutes, and deafens",
    LogCategory.CHANNELS: "Logs for channel creates, deletes, and updates",
    LogCategory.THREADS: "Logs for thread and forum post creates, archives, and deletes",
    LogCategory.ROLES: "Logs for role creates, deletes, and updates",
    LogCategory.EMOJI_STICKERS: "Logs for emoji and sticker changes",
    LogCategory.SERVER_SETTINGS: "Logs for server setting changes",
    LogCategory.PERMISSIONS: "Logs for permission overwrite changes",
    LogCategory.BOTS_INTEGRATIONS: "Logs for bot, webhook, and integration changes",
    LogCategory.AUTOMOD: "Logs for AutoMod actions and blocked messages",
    LogCategory.EVENTS: "Logs for scheduled event creates, updates, and deletes",
    LogCategory.REACTIONS: "Logs for reaction adds and removes",
    LogCategory.STAGE: "Logs for stage channel activity and speakers",
    LogCategory.BOOSTS: "Logs for server boost and unboost events",
    LogCategory.INVITES: "Logs for invite creates, deletes, and usage details",
    LogCategory.ALERTS: "Security alerts for raids, suspicious activity, and threats",
    LogCategory.ALLIANCES: "Logs for alliance message links and auto-deletions on member leave",
    LogCategory.TICKETS: "Logs for ticket creates, claims, closes, reopens, and user additions",
    LogCategory.TRANSCRIPTS: "Full conversation transcripts of closed tickets and approved cases",
    LogCategory.APPEALS: "Logs for appeal creates, approvals, denials, and reopens",
    LogCategory.WARNINGS: "Logs for user warnings issued by moderators",
}


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["LogCategory", "THREAD_DESCRIPTIONS"]
