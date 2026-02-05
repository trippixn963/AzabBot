"""
AzabBot - Timeouts, Kicks, and Audit Log Mixin
===============================================

Database operations for timeout/kick tracking and permanent audit log.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


class TimeoutsMixin:
    """Mixin for timeout, kick, and audit log database operations."""

    # =========================================================================
    # Timeout Operations
    # =========================================================================

    def add_timeout(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        until_timestamp: Optional[float] = None,
    ) -> int:
        """
        Record a timeout in the database.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            moderator_id: Moderator who applied the timeout.
            reason: Optional reason for the timeout.
            duration_seconds: Duration in seconds.
            until_timestamp: Discord's timeout_until timestamp.

        Returns:
            The row ID of the inserted record.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO timeout_history
               (user_id, guild_id, moderator_id, action, reason, duration_seconds, until_timestamp, timestamp)
               VALUES (?, ?, ?, 'timeout', ?, ?, ?, ?)""",
            (user_id, guild_id, moderator_id, reason, duration_seconds, until_timestamp, now)
        )

        logger.tree("TIMEOUT RECORDED", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
            ("Duration", f"{duration_seconds}s" if duration_seconds else "Unknown"),
        ], emoji="⏱️")

        return cursor.lastrowid

    def remove_timeout(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
    ) -> int:
        """
        Record a timeout removal in the database.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            moderator_id: Moderator who removed the timeout.
            reason: Optional reason for removal.

        Returns:
            The row ID of the inserted record.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO timeout_history
               (user_id, guild_id, moderator_id, action, reason, duration_seconds, until_timestamp, timestamp)
               VALUES (?, ?, ?, 'untimeout', ?, NULL, NULL, ?)""",
            (user_id, guild_id, moderator_id, reason, now)
        )

        logger.tree("UNTIMEOUT RECORDED", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
        ], emoji="⏱️")

        return cursor.lastrowid

    def get_user_timeout_history(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get timeout history for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.

        Returns:
            List of timeout history records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM timeout_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

    def get_user_timeout_count(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
    ) -> int:
        """
        Get total timeout count for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Number of timeouts.
        """
        row = self.fetchone(
            """SELECT COUNT(*) as count FROM timeout_history
               WHERE user_id = ? AND guild_id = ? AND action = 'timeout'""",
            (user_id, guild_id)
        )
        return row["count"] if row else 0

    # =========================================================================
    # Kick Operations
    # =========================================================================

    def add_kick(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
    ) -> int:
        """
        Record a kick in the database.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            moderator_id: Moderator who performed the kick.
            reason: Optional reason for the kick.

        Returns:
            The row ID of the inserted record.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO kick_history
               (user_id, guild_id, moderator_id, reason, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, guild_id, moderator_id, reason, now)
        )

        logger.tree("KICK RECORDED", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
            ("Reason", (reason or "None")[:50]),
        ], emoji="👢")

        return cursor.lastrowid

    def get_user_kick_history(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get kick history for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.

        Returns:
            List of kick history records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM kick_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

    def get_user_kick_count(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
    ) -> int:
        """
        Get total kick count for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Number of kicks.
        """
        row = self.fetchone(
            """SELECT COUNT(*) as count FROM kick_history
               WHERE user_id = ? AND guild_id = ?""",
            (user_id, guild_id)
        )
        return row["count"] if row else 0

    # =========================================================================
    # Audit Log Operations (Permanent - Never Decays)
    # =========================================================================

    def log_moderation_action(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        moderator_id: int,
        action_type: str,
        action_source: str,
        reason: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        case_id: Optional[str] = None,
    ) -> int:
        """
        Log a moderation action to the permanent audit log.

        Args:
            user_id: Discord user ID of the target.
            guild_id: Guild ID.
            moderator_id: Moderator/bot who performed the action.
            action_type: Type of action (mute, unmute, ban, unban, kick, timeout, untimeout, warn).
            action_source: Source of action (manual, auto_spam, auto_religion, auto_vc, auto_ping_spam, auto_invite, scheduled).
            reason: Optional reason for the action.
            duration_seconds: Optional duration for timed actions.
            details: Optional JSON-serializable dict with extra data.
            case_id: Optional link to cases table.

        Returns:
            The row ID of the inserted record.
        """
        now = time.time()
        details_json = json.dumps(details) if details else None

        cursor = self.execute(
            """INSERT INTO moderation_audit_log
               (user_id, guild_id, moderator_id, action_type, action_source, reason, duration_seconds, details, case_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, moderator_id, action_type, action_source, reason, duration_seconds, details_json, case_id, now)
        )

        logger.tree("AUDIT LOG ENTRY", [
            ("User ID", str(user_id)),
            ("Action", action_type),
            ("Source", action_source),
            ("Moderator ID", str(moderator_id)),
        ], emoji="📝")

        return cursor.lastrowid

    def get_audit_log(
        self: "DatabaseManager",
        guild_id: int,
        limit: int = 50,
        offset: int = 0,
        action_type: Optional[str] = None,
        action_source: Optional[str] = None,
        user_id: Optional[int] = None,
        moderator_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get audit log entries with optional filters.

        Args:
            guild_id: Guild ID.
            limit: Maximum records to return.
            offset: Number of records to skip.
            action_type: Optional filter by action type.
            action_source: Optional filter by action source.
            user_id: Optional filter by target user.
            moderator_id: Optional filter by moderator.

        Returns:
            List of audit log records, newest first.
        """
        query = "SELECT * FROM moderation_audit_log WHERE guild_id = ?"
        params: List[Any] = [guild_id]

        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)

        if action_source:
            query += " AND action_source = ?"
            params.append(action_source)

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        if moderator_id:
            query += " AND moderator_id = ?"
            params.append(moderator_id)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.fetchall(query, tuple(params))

        result = []
        for row in rows:
            record = dict(row)
            # Parse JSON details if present
            if record.get("details"):
                try:
                    record["details"] = json.loads(record["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(record)

        return result

    def get_user_audit_history(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Get complete audit history for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.

        Returns:
            List of audit log records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM moderation_audit_log
               WHERE user_id = ? AND guild_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )

        result = []
        for row in rows:
            record = dict(row)
            if record.get("details"):
                try:
                    record["details"] = json.loads(record["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(record)

        return result

    def get_audit_log_count(
        self: "DatabaseManager",
        guild_id: int,
        action_type: Optional[str] = None,
    ) -> int:
        """
        Get count of audit log entries.

        Args:
            guild_id: Guild ID.
            action_type: Optional filter by action type.

        Returns:
            Count of matching records.
        """
        if action_type:
            row = self.fetchone(
                """SELECT COUNT(*) as count FROM moderation_audit_log
                   WHERE guild_id = ? AND action_type = ?""",
                (guild_id, action_type)
            )
        else:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM moderation_audit_log WHERE guild_id = ?",
                (guild_id,)
            )
        return row["count"] if row else 0


__all__ = ["TimeoutsMixin"]
