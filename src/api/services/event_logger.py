"""
AzabBot - Event Logger
======================

Unified logging service for Discord events.
Handles both console logging (logger.tree) and dashboard storage (SQLite).

Single call logs to both destinations:
    event_logger.log_ban(guild, target, moderator, reason)
    # -> Console: tree log with emoji
    # -> Dashboard: SQLite + WebSocket broadcast

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any, Dict, List, Optional, Tuple, Union

import discord

from src.core.logger import logger
from src.api.services.event_storage import get_event_storage, EventType


# =============================================================================
# Helpers
# =============================================================================

def _safe_log(func):
    """Decorator to safely log events without breaking the caller."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.debug("Event Log Failed", [
                ("Function", func.__name__),
                ("Error", str(e)[:50]),
            ])
            return 0
    return wrapper


def _get_avatar_url(user: Union[discord.User, discord.Member, None]) -> Optional[str]:
    """Get the avatar URL for a user (guild avatar if available)."""
    if not user:
        return None
    return user.display_avatar.url


def _get_display_name(user: Union[discord.User, discord.Member, None]) -> Optional[str]:
    """Get the display name for a user."""
    if not user:
        return None
    if isinstance(user, discord.Member) and user.nick:
        return f"{user.nick} ({user.name})"
    return user.name


def _user_str(user: Union[discord.User, discord.Member, None]) -> str:
    """Format user for console logging: 'name (id)'"""
    if not user:
        return "Unknown"
    return f"{user.name} ({user.id})"


def _truncate(text: Optional[str], max_len: int = 50) -> str:
    """Truncate text for console display."""
    if not text:
        return "(empty)"
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


# =============================================================================
# Event Logger
# =============================================================================

class EventLogger:
    """
    Unified event logger for Discord events.

    Each method logs to:
    1. Console via logger.tree() - for real-time monitoring
    2. SQLite via event_storage - for dashboard display
    3. WebSocket broadcast - for real-time dashboard updates

    Usage:
        from src.api.services.event_logger import event_logger

        event_logger.log_ban(guild, target, moderator, reason)
    """

    def __init__(self):
        self._storage = None

    @property
    def storage(self):
        """Lazy-load storage to avoid import issues."""
        if self._storage is None:
            self._storage = get_event_storage()
        return self._storage

    def _log(
        self,
        title: str,
        emoji: str,
        fields: List[Tuple[str, str]],
        event_type: str,
        guild_id: int,
        actor_id: Optional[int] = None,
        actor_name: Optional[str] = None,
        actor_avatar: Optional[str] = None,
        target_id: Optional[int] = None,
        target_name: Optional[str] = None,
        target_avatar: Optional[str] = None,
        channel_id: Optional[int] = None,
        channel_name: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Internal method to log to both console and storage.

        Returns:
            Event ID from storage
        """
        # Console log
        logger.tree(title, fields, emoji=emoji)

        # Storage log (triggers WebSocket broadcast via callback)
        return self.storage.add(
            event_type=event_type,
            guild_id=guild_id,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_avatar=actor_avatar,
            target_id=target_id,
            target_name=target_name,
            target_avatar=target_avatar,
            channel_id=channel_id,
            channel_name=channel_name,
            reason=reason,
            details=details,
        )

    # =========================================================================
    # Member Events
    # =========================================================================

    @_safe_log
    def log_ban(
        self,
        guild: discord.Guild,
        target: Union[discord.User, discord.Member],
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> int:
        """Log a member ban event."""
        fields = [
            ("Target", _user_str(target)),
        ]
        if moderator:
            fields.append(("Moderator", _user_str(moderator)))
        if reason:
            fields.append(("Reason", _truncate(reason, 80)))

        return self._log(
            title="MEMBER BANNED",
            emoji="🔨",
            fields=fields,
            event_type=EventType.MEMBER_BAN,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            reason=reason,
        )

    @_safe_log
    def log_unban(
        self,
        guild: discord.Guild,
        target: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> int:
        """Log a member unban event."""
        fields = [
            ("Target", _user_str(target)),
        ]
        if moderator:
            fields.append(("Moderator", _user_str(moderator)))
        if reason:
            fields.append(("Reason", _truncate(reason, 80)))

        return self._log(
            title="MEMBER UNBANNED",
            emoji="🔓",
            fields=fields,
            event_type=EventType.MEMBER_UNBAN,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            reason=reason,
        )

    @_safe_log
    def log_kick(
        self,
        guild: discord.Guild,
        target: Union[discord.User, discord.Member],
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> int:
        """Log a member kick event."""
        fields = [
            ("Target", _user_str(target)),
        ]
        if moderator:
            fields.append(("Moderator", _user_str(moderator)))
        if reason:
            fields.append(("Reason", _truncate(reason, 80)))

        return self._log(
            title="MEMBER KICKED",
            emoji="👢",
            fields=fields,
            event_type=EventType.MEMBER_KICK,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            reason=reason,
        )

    @_safe_log
    def log_timeout(
        self,
        guild: discord.Guild,
        target: discord.Member,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        until: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> int:
        """Log a member timeout event."""
        fields = [
            ("Target", _user_str(target)),
        ]
        if moderator:
            fields.append(("Moderator", _user_str(moderator)))
        if until:
            fields.append(("Until", str(until)))
        if reason:
            fields.append(("Reason", _truncate(reason, 80)))

        details = {}
        if until:
            details["until"] = str(until)
        if duration_seconds:
            details["duration_seconds"] = duration_seconds

        return self._log(
            title="MEMBER TIMED OUT",
            emoji="⏱️",
            fields=fields,
            event_type=EventType.MEMBER_TIMEOUT,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            reason=reason,
            details=details if details else None,
        )

    @_safe_log
    def log_timeout_remove(
        self,
        guild: discord.Guild,
        target: discord.Member,
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a timeout removal event."""
        fields = [
            ("Target", _user_str(target)),
        ]
        if moderator:
            fields.append(("Moderator", _user_str(moderator)))

        return self._log(
            title="TIMEOUT REMOVED",
            emoji="✅",
            fields=fields,
            event_type=EventType.MEMBER_TIMEOUT_REMOVE,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
        )

    @_safe_log
    def log_join(
        self,
        member: discord.Member,
        invite_code: Optional[str] = None,
        inviter: Optional[discord.User] = None,
    ) -> int:
        """Log a member join event."""
        account_age = (discord.utils.utcnow() - member.created_at).days

        fields = [
            ("Member", _user_str(member)),
            ("Account Age", f"{account_age} days"),
        ]
        if invite_code:
            fields.append(("Invite", invite_code))
        if inviter:
            fields.append(("Inviter", _user_str(inviter)))

        details = {"account_age_days": account_age}
        if invite_code:
            details["invite_code"] = invite_code
        if inviter:
            details["inviter_id"] = inviter.id
            details["inviter_name"] = str(inviter)

        return self._log(
            title="MEMBER JOINED",
            emoji="📥",
            fields=fields,
            event_type=EventType.MEMBER_JOIN,
            guild_id=member.guild.id,
            target_id=member.id,
            target_name=_get_display_name(member),
            target_avatar=_get_avatar_url(member),
            details=details,
        )

    @_safe_log
    def log_leave(
        self,
        member: discord.Member,
        roles: Optional[list] = None,
        membership_duration: Optional[str] = None,
    ) -> int:
        """Log a member leave event."""
        fields = [
            ("Member", _user_str(member)),
        ]
        if membership_duration:
            fields.append(("Membership", membership_duration))

        details = {}
        if roles:
            role_names = [r.name for r in roles if r.name != "@everyone"]
            if role_names:
                details["roles"] = role_names
                fields.append(("Roles", str(len(role_names))))

        return self._log(
            title="MEMBER LEFT",
            emoji="📤",
            fields=fields,
            event_type=EventType.MEMBER_LEAVE,
            guild_id=member.guild.id,
            target_id=member.id,
            target_name=_get_display_name(member),
            target_avatar=_get_avatar_url(member),
            details=details if details else None,
        )

    @_safe_log
    def log_role_add(
        self,
        guild: discord.Guild,
        target: discord.Member,
        role: discord.Role,
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a role add event."""
        fields = [
            ("Target", _user_str(target)),
            ("Role", role.name),
        ]
        if moderator:
            fields.append(("By", _user_str(moderator)))

        return self._log(
            title="ROLE ADDED",
            emoji="🏷️",
            fields=fields,
            event_type=EventType.MEMBER_ROLE_ADD,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            details={"role_name": role.name, "role_id": str(role.id)},
        )

    @_safe_log
    def log_role_remove(
        self,
        guild: discord.Guild,
        target: discord.Member,
        role: discord.Role,
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a role remove event."""
        fields = [
            ("Target", _user_str(target)),
            ("Role", role.name),
        ]
        if moderator:
            fields.append(("By", _user_str(moderator)))

        return self._log(
            title="ROLE REMOVED",
            emoji="🏷️",
            fields=fields,
            event_type=EventType.MEMBER_ROLE_REMOVE,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            details={"role_name": role.name, "role_id": str(role.id)},
        )

    @_safe_log
    def log_nick_change(
        self,
        guild: discord.Guild,
        target: discord.Member,
        old_nick: Optional[str],
        new_nick: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a nickname change event."""
        fields = [
            ("Target", _user_str(target)),
            ("Old", old_nick or "(none)"),
            ("New", new_nick or "(none)"),
        ]
        if moderator:
            fields.append(("By", _user_str(moderator)))

        return self._log(
            title="NICKNAME CHANGED",
            emoji="✏️",
            fields=fields,
            event_type=EventType.MEMBER_NICK_CHANGE,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            details={"old_nick": old_nick, "new_nick": new_nick},
        )

    # =========================================================================
    # Message Events
    # =========================================================================

    @_safe_log
    def log_message_delete(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        author: Union[discord.User, discord.Member],
        content: Optional[str] = None,
        moderator: Optional[discord.Member] = None,
        attachments: Optional[list] = None,
    ) -> int:
        """Log a message delete event."""
        fields = [
            ("Author", _user_str(author)),
            ("Channel", f"#{channel.name}"),
        ]
        if content:
            fields.append(("Content", _truncate(content, 60)))
        if attachments:
            fields.append(("Attachments", str(len(attachments))))
        if moderator:
            fields.append(("Deleted By", _user_str(moderator)))

        details = {}
        if content:
            details["content"] = content[:1000]
        if attachments:
            details["attachments"] = attachments[:5]

        return self._log(
            title="MESSAGE DELETED",
            emoji="🗑️",
            fields=fields,
            event_type=EventType.MESSAGE_DELETE,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=author.id,
            target_name=_get_display_name(author),
            target_avatar=_get_avatar_url(author),
            channel_id=channel.id,
            channel_name=channel.name,
            details=details if details else None,
        )

    @_safe_log
    def log_bulk_delete(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        count: int,
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a bulk message delete event."""
        fields = [
            ("Channel", f"#{channel.name}"),
            ("Count", str(count)),
        ]
        if moderator:
            fields.append(("Deleted By", _user_str(moderator)))

        return self._log(
            title="BULK DELETE",
            emoji="🗑️",
            fields=fields,
            event_type=EventType.MESSAGE_BULK_DELETE,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            channel_id=channel.id,
            channel_name=channel.name,
            details={"count": count},
        )

    # =========================================================================
    # Voice Events
    # =========================================================================

    @_safe_log
    def log_voice_disconnect(
        self,
        guild: discord.Guild,
        target: discord.Member,
        channel_name: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> int:
        """Log a voice disconnect event."""
        fields = [
            ("Target", _user_str(target)),
            ("Channel", channel_name),
        ]
        if moderator:
            fields.append(("By", _user_str(moderator)))

        return self._log(
            title="VOICE DISCONNECT",
            emoji="🔇",
            fields=fields,
            event_type=EventType.VOICE_DISCONNECT,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            channel_id=channel_id,
            channel_name=channel_name,
        )

    @_safe_log
    def log_voice_mute(
        self,
        guild: discord.Guild,
        target: discord.Member,
        muted: bool,
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a voice mute/unmute event."""
        action = "MUTED" if muted else "UNMUTED"
        fields = [
            ("Target", _user_str(target)),
        ]
        if moderator:
            fields.append(("By", _user_str(moderator)))

        return self._log(
            title=f"VOICE {action}",
            emoji="🔇" if muted else "🔊",
            fields=fields,
            event_type=EventType.VOICE_MUTE,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            details={"muted": muted},
        )

    @_safe_log
    def log_voice_deafen(
        self,
        guild: discord.Guild,
        target: discord.Member,
        deafened: bool,
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a voice deafen/undeafen event."""
        action = "DEAFENED" if deafened else "UNDEAFENED"
        fields = [
            ("Target", _user_str(target)),
        ]
        if moderator:
            fields.append(("By", _user_str(moderator)))

        return self._log(
            title=f"VOICE {action}",
            emoji="🔇" if deafened else "🔊",
            fields=fields,
            event_type=EventType.VOICE_DEAFEN,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=target.id,
            target_name=_get_display_name(target),
            target_avatar=_get_avatar_url(target),
            details={"deafened": deafened},
        )

    # =========================================================================
    # Channel Events
    # =========================================================================

    @_safe_log
    def log_channel_update(
        self,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a channel update event."""
        fields = [
            ("Channel", f"#{channel.name}"),
            ("Changes", _truncate(changes, 80)),
        ]
        if moderator:
            fields.append(("By", _user_str(moderator)))

        return self._log(
            title="CHANNEL UPDATED",
            emoji="📁",
            fields=fields,
            event_type=EventType.CHANNEL_UPDATE,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            channel_id=channel.id,
            channel_name=channel.name,
            details={"changes": changes},
        )

    # =========================================================================
    # Server Events
    # =========================================================================

    @_safe_log
    def log_bot_add(
        self,
        guild: discord.Guild,
        bot: discord.Member,
        moderator: Optional[discord.Member] = None,
    ) -> int:
        """Log a bot add event."""
        fields = [
            ("Bot", _user_str(bot)),
        ]
        if moderator:
            fields.append(("Added By", _user_str(moderator)))

        return self._log(
            title="BOT ADDED",
            emoji="🤖",
            fields=fields,
            event_type=EventType.BOT_ADD,
            guild_id=guild.id,
            actor_id=moderator.id if moderator else None,
            actor_name=_get_display_name(moderator),
            actor_avatar=_get_avatar_url(moderator),
            target_id=bot.id,
            target_name=_get_display_name(bot),
            target_avatar=_get_avatar_url(bot),
        )

    # =========================================================================
    # Generic Event
    # =========================================================================

    @_safe_log
    def log_event(
        self,
        title: str,
        emoji: str,
        fields: List[Tuple[str, str]],
        event_type: str,
        guild_id: int,
        actor_id: Optional[int] = None,
        actor_name: Optional[str] = None,
        actor_avatar: Optional[str] = None,
        target_id: Optional[int] = None,
        target_name: Optional[str] = None,
        target_avatar: Optional[str] = None,
        channel_id: Optional[int] = None,
        channel_name: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Log a custom event with full control over all fields."""
        return self._log(
            title=title,
            emoji=emoji,
            fields=fields,
            event_type=event_type,
            guild_id=guild_id,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_avatar=actor_avatar,
            target_id=target_id,
            target_name=target_name,
            target_avatar=target_avatar,
            channel_id=channel_id,
            channel_name=channel_name,
            reason=reason,
            details=details,
        )


# Singleton instance
event_logger = EventLogger()


__all__ = ["EventLogger", "event_logger", "EventType"]
