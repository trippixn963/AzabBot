"""
AzabBot - Database Lockdown Operations Module
=============================================

Lockdown, spam violations, and forbid database operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from src.core.logger import logger

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class LockdownMixin:
    """Mixin for lockdown and restriction database operations."""

    # Lockdown Operations
    # =========================================================================

    def start_lockdown(
        self,
        guild_id: int,
        locked_by: int,
        reason: Optional[str] = None,
        channel_count: int = 0
    ) -> None:
        """
        Record a server lockdown.

        Args:
            guild_id: Guild being locked.
            locked_by: Moderator who initiated lockdown.
            reason: Reason for lockdown.
            channel_count: Number of channels locked.
        """
        self.execute(
            """INSERT OR REPLACE INTO lockdown_state
               (guild_id, locked_at, locked_by, reason, channel_count)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, time.time(), locked_by, reason, channel_count)
        )

        logger.tree("Lockdown Started", [
            ("Guild ID", str(guild_id)),
            ("Locked By", str(locked_by)),
            ("Channels", str(channel_count)),
        ], emoji="🔒")

    def end_lockdown(self: "DatabaseManager", guild_id: int) -> None:
        """
        End a server lockdown and clear saved permissions.

        Args:
            guild_id: Guild to unlock.
        """
        self.execute("DELETE FROM lockdown_state WHERE guild_id = ?", (guild_id,))
        self.execute("DELETE FROM lockdown_permissions WHERE guild_id = ?", (guild_id,))

        logger.tree("Lockdown Ended", [
            ("Guild ID", str(guild_id)),
        ], emoji="🔓")

    def is_locked(self: "DatabaseManager", guild_id: int) -> bool:
        """
        Check if a guild is currently locked.

        Args:
            guild_id: Guild to check.

        Returns:
            True if guild is locked.
        """
        row = self.fetchone(
            "SELECT 1 FROM lockdown_state WHERE guild_id = ?",
            (guild_id,)
        )
        return row is not None

    def get_lockdown_state(self: "DatabaseManager", guild_id: int) -> Optional[Dict[str, Any]]:
        """
        Get lockdown state for a guild.

        Args:
            guild_id: Guild to check.

        Returns:
            Lockdown info dict or None if not locked.
        """
        row = self.fetchone(
            "SELECT * FROM lockdown_state WHERE guild_id = ?",
            (guild_id,)
        )
        return dict(row) if row else None

    def save_channel_permission(
        self,
        guild_id: int,
        channel_id: int,
        channel_type: str,
        send_messages: Optional[bool],
        connect: Optional[bool]
    ) -> None:
        """
        Save original channel permission before lockdown.

        Args:
            guild_id: Guild ID.
            channel_id: Channel ID.
            channel_type: 'text' or 'voice'.
            send_messages: Original send_messages permission (None, True, False).
            connect: Original connect permission (None, True, False).
        """
        # Convert bool/None to int for storage (None=NULL, True=1, False=0)
        send_int = None if send_messages is None else (1 if send_messages else 0)
        connect_int = None if connect is None else (1 if connect else 0)

        self.execute(
            """INSERT OR REPLACE INTO lockdown_permissions
               (guild_id, channel_id, channel_type, original_send_messages, original_connect)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, channel_id, channel_type, send_int, connect_int)
        )

        logger.debug("Channel Permission Saved", [
            ("Channel ID", str(channel_id)),
            ("Type", channel_type),
        ])

    def get_channel_permissions(self: "DatabaseManager", guild_id: int) -> List[Dict[str, Any]]:
        """
        Get all saved channel permissions for a guild.

        Args:
            guild_id: Guild to get permissions for.

        Returns:
            List of permission records.
        """
        rows = self.fetchall(
            "SELECT * FROM lockdown_permissions WHERE guild_id = ?",
            (guild_id,)
        )
        result = []
        for row in rows:
            record = dict(row)
            # Convert stored ints back to bool/None
            send = record.get("original_send_messages")
            connect = record.get("original_connect")
            record["original_send_messages"] = None if send is None else bool(send)
            record["original_connect"] = None if connect is None else bool(connect)
            result.append(record)
        return result

    def clear_lockdown_permissions(self: "DatabaseManager", guild_id: int) -> None:
        """
        Clear saved channel permissions for a guild.

        Args:
            guild_id: Guild to clear permissions for.
        """
        self.execute("DELETE FROM lockdown_permissions WHERE guild_id = ?", (guild_id,))
        self.execute("DELETE FROM lockdown_role_permissions WHERE guild_id = ?", (guild_id,))

        logger.debug("Lockdown Permissions Cleared", [
            ("Guild ID", str(guild_id)),
        ])

    # =========================================================================
    # Role-Based Lockdown Operations
    # =========================================================================

    def save_lockdown_permissions(
        self,
        guild_id: int,
        send_messages: bool,
        connect: bool,
        add_reactions: bool,
        create_public_threads: bool,
        create_private_threads: bool,
        send_messages_in_threads: bool,
    ) -> None:
        """
        Save original @everyone role permissions before lockdown.

        Args:
            guild_id: Guild ID.
            send_messages: Original send_messages permission.
            connect: Original connect permission.
            add_reactions: Original add_reactions permission.
            create_public_threads: Original create_public_threads permission.
            create_private_threads: Original create_private_threads permission.
            send_messages_in_threads: Original send_messages_in_threads permission.
        """
        self.execute(
            """INSERT OR REPLACE INTO lockdown_role_permissions
               (guild_id, send_messages, connect, add_reactions,
                create_public_threads, create_private_threads, send_messages_in_threads)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                guild_id,
                1 if send_messages else 0,
                1 if connect else 0,
                1 if add_reactions else 0,
                1 if create_public_threads else 0,
                1 if create_private_threads else 0,
                1 if send_messages_in_threads else 0,
            )
        )

        logger.debug("Role Permissions Saved", [
            ("Guild ID", str(guild_id)),
        ])

    def get_lockdown_permissions(self: "DatabaseManager", guild_id: int) -> Optional[Dict[str, bool]]:
        """
        Get saved @everyone role permissions for a guild.

        Args:
            guild_id: Guild to get permissions for.

        Returns:
            Dict with permission booleans or None if not found.
        """
        row = self.fetchone(
            "SELECT * FROM lockdown_role_permissions WHERE guild_id = ?",
            (guild_id,)
        )
        if not row:
            return None
        return {
            "send_messages": bool(row["send_messages"]),
            "connect": bool(row["connect"]),
            "add_reactions": bool(row["add_reactions"]),
            "create_public_threads": bool(row["create_public_threads"]),
            "create_private_threads": bool(row["create_private_threads"]),
            "send_messages_in_threads": bool(row["send_messages_in_threads"]),
        }


    # =========================================================================
    # Spam Violations Operations
    # =========================================================================

    def get_spam_violations(self: "DatabaseManager", user_id: int, guild_id: int) -> Dict[str, Any]:
        """
        Get spam violation record for a user.

        Args:
            user_id: User ID
            guild_id: Guild ID

        Returns:
            Dict with violation_count, last_violation_at, last_spam_type
            or defaults if no record exists
        """
        row = self.fetchone(
            "SELECT violation_count, last_violation_at, last_spam_type "
            "FROM spam_violations WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        if row:
            return {
                "violation_count": row["violation_count"],
                "last_violation_at": row["last_violation_at"],
                "last_spam_type": row["last_spam_type"],
            }
        return {
            "violation_count": 0,
            "last_violation_at": None,
            "last_spam_type": None,
        }

    def add_spam_violation(
        self,
        user_id: int,
        guild_id: int,
        spam_type: str,
    ) -> int:
        """
        Add or increment spam violation for a user.

        Args:
            user_id: User ID
            guild_id: Guild ID
            spam_type: Type of spam detected

        Returns:
            New violation count
        """
        now = time.time()
        existing = self.get_spam_violations(user_id, guild_id)

        if existing["violation_count"] > 0:
            new_count = existing["violation_count"] + 1
            self.execute(
                "UPDATE spam_violations SET violation_count = ?, "
                "last_violation_at = ?, last_spam_type = ? "
                "WHERE user_id = ? AND guild_id = ?",
                (new_count, now, spam_type, user_id, guild_id)
            )
        else:
            new_count = 1
            self.execute(
                "INSERT INTO spam_violations "
                "(user_id, guild_id, violation_count, last_violation_at, last_spam_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, guild_id, 1, now, spam_type)
            )

        logger.tree("Spam Violation Recorded", [
            ("User ID", str(user_id)),
            ("Type", spam_type),
            ("Count", str(new_count)),
        ], emoji="🚫")

        return new_count

    def decay_spam_violations(self: "DatabaseManager", decay_seconds: int = 300) -> int:
        """
        Decay violations for users who haven't violated in a while.

        Args:
            decay_seconds: Time since last violation to decay (default 5 min)

        Returns:
            Number of records affected
        """
        cutoff = time.time() - decay_seconds
        # Decrement by 1, delete if reaches 0
        self.execute(
            "UPDATE spam_violations SET violation_count = violation_count - 1 "
            "WHERE last_violation_at < ? AND violation_count > 0",
            (cutoff,)
        )
        # Clean up zero violations
        result = self.execute(
            "DELETE FROM spam_violations WHERE violation_count <= 0"
        )
        return result.rowcount if result else 0

    def reset_spam_violations(self: "DatabaseManager", user_id: int, guild_id: int) -> None:
        """
        Reset spam violations for a user (e.g., after manual review).

        Args:
            user_id: User ID
            guild_id: Guild ID
        """
        self.execute(
            "DELETE FROM spam_violations WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )

        logger.debug("Spam Violations Reset", [
            ("User ID", str(user_id)),
            ("Guild ID", str(guild_id)),
        ])

    # =========================================================================
    # Forbid Operations
    # =========================================================================

    def add_forbid(
        self,
        user_id: int,
        guild_id: int,
        restriction_type: str,
        moderator_id: int,
        reason: Optional[str] = None,
        expires_at: Optional[float] = None,
        case_id: Optional[str] = None,
    ) -> bool:
        """
        Add a restriction to a user.

        Returns True if added, False if already exists.
        """
        now = time.time()
        try:
            self.execute(
                """INSERT OR REPLACE INTO forbid_history
                   (user_id, guild_id, restriction_type, moderator_id, reason, created_at, expires_at, removed_at, removed_by, case_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (user_id, guild_id, restriction_type, moderator_id, reason, now, expires_at, case_id)
            )

            logger.tree("Forbid Added", [
                ("User ID", str(user_id)),
                ("Type", restriction_type),
                ("Moderator", str(moderator_id)),
                ("Expires", str(expires_at) if expires_at else "Never"),
            ], emoji="🚫")

            return True
        except Exception:
            return False

    def get_expired_forbids(self: "DatabaseManager") -> List[Dict[str, Any]]:
        """Get all forbids that have expired but not yet removed."""
        now = time.time()
        rows = self.fetchall(
            """SELECT id, user_id, guild_id, restriction_type, moderator_id, reason, created_at, expires_at
               FROM forbid_history
               WHERE expires_at IS NOT NULL AND expires_at <= ? AND removed_at IS NULL""",
            (now,)
        )
        return [dict(row) for row in rows]

    def update_forbid_case_id(
        self,
        user_id: int,
        guild_id: int,
        restriction_type: str,
        case_id: str,
    ) -> bool:
        """Update the case_id for a forbid entry."""
        cursor = self.execute(
            """UPDATE forbid_history SET case_id = ?
               WHERE user_id = ? AND guild_id = ? AND restriction_type = ? AND removed_at IS NULL""",
            (case_id, user_id, guild_id, restriction_type)
        )

        if cursor.rowcount > 0:
            logger.debug("Forbid Case ID Updated", [
                ("User ID", str(user_id)),
                ("Type", restriction_type),
                ("Case ID", case_id),
            ])

        return cursor.rowcount > 0

    def remove_forbid(
        self,
        user_id: int,
        guild_id: int,
        restriction_type: str,
        removed_by: int,
    ) -> bool:
        """
        Remove a restriction from a user.

        Returns True if removed, False if didn't exist.
        """
        now = time.time()
        cursor = self.execute(
            """UPDATE forbid_history
               SET removed_at = ?, removed_by = ?
               WHERE user_id = ? AND guild_id = ? AND restriction_type = ? AND removed_at IS NULL""",
            (now, removed_by, user_id, guild_id, restriction_type)
        )

        if cursor.rowcount > 0:
            logger.tree("Forbid Removed", [
                ("User ID", str(user_id)),
                ("Type", restriction_type),
                ("Removed By", str(removed_by)),
            ], emoji="✅")

        return cursor.rowcount > 0

    def get_user_forbids(self: "DatabaseManager", user_id: int, guild_id: int) -> List[Dict[str, Any]]:
        """
        Get all active restrictions for a user.

        Returns list of restriction records.
        """
        rows = self.fetchall(
            """SELECT restriction_type, moderator_id, reason, created_at
               FROM forbid_history
               WHERE user_id = ? AND guild_id = ? AND removed_at IS NULL
               ORDER BY created_at DESC""",
            (user_id, guild_id)
        )
        return [dict(row) for row in rows]

    def get_forbid_history(self: "DatabaseManager", user_id: int, guild_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get full forbid history for a user (including removed).

        Returns list of all restriction records.
        """
        rows = self.fetchall(
            """SELECT restriction_type, moderator_id, reason, created_at, removed_at, removed_by
               FROM forbid_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

    def is_forbidden(self: "DatabaseManager", user_id: int, guild_id: int, restriction_type: str) -> bool:
        """Check if user has a specific active restriction."""
        row = self.fetchone(
            """SELECT 1 FROM forbid_history
               WHERE user_id = ? AND guild_id = ? AND restriction_type = ? AND removed_at IS NULL""",
            (user_id, guild_id, restriction_type)
        )
        return row is not None


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["LockdownMixin"]
