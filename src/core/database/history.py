"""
AzabBot - History Operations Mixin
==================================

Nickname, username, and combined history operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


class HistoryMixin:
    """Mixin for nickname, username, and combined history operations."""

    # =========================================================================
    # Nickname History Operations
    # =========================================================================

    def save_nickname_change(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        old_nickname: Optional[str],
        new_nickname: Optional[str],
        changed_by: Optional[int] = None,
    ) -> None:
        """
        Save a nickname change to history.

        Args:
            user_id: Discord user ID whose nickname changed.
            guild_id: Guild where the change occurred.
            old_nickname: Previous nickname (None if no nickname).
            new_nickname: New nickname (None if cleared).
            changed_by: User ID who made the change (None if self).
        """
        now = time.time()
        self.execute(
            """INSERT INTO nickname_history
               (user_id, guild_id, old_nickname, new_nickname, changed_by, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, old_nickname, new_nickname, changed_by, now)
        )

        logger.debug("Nickname Change Saved", [
            ("User ID", str(user_id)),
            ("Old", (old_nickname or "None")[:20]),
            ("New", (new_nickname or "None")[:20]),
        ])

    def get_nickname_history(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get nickname history for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.

        Returns:
            List of nickname history records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM nickname_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY changed_at DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

    def get_all_nicknames(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
    ) -> List[str]:
        """
        Get all unique nicknames a user has had.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            List of unique nicknames (excluding None).
        """
        rows = self.fetchall(
            """SELECT DISTINCT old_nickname FROM nickname_history
               WHERE user_id = ? AND guild_id = ? AND old_nickname IS NOT NULL
               UNION
               SELECT DISTINCT new_nickname FROM nickname_history
               WHERE user_id = ? AND guild_id = ? AND new_nickname IS NOT NULL""",
            (user_id, guild_id, user_id, guild_id)
        )
        return [row["old_nickname"] or row["new_nickname"] for row in rows if row[0]]

    # =========================================================================
    # Username History Operations
    # =========================================================================

    def save_username_change(
        self: "DatabaseManager",
        user_id: int,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        guild_id: Optional[int] = None,
    ) -> int:
        """
        Save a username or nickname change to history.

        Automatically maintains a rolling window of 10 entries per user.
        Ignores AFK nicknames (containing "[AFK]").

        Args:
            user_id: Discord user ID.
            username: Global username (if changed).
            display_name: Server nickname (if changed).
            guild_id: Guild ID for nickname changes (None for global).

        Returns:
            The row ID of the inserted record, or 0 if skipped.
        """
        # Skip AFK nicknames - these are temporary and not real name changes
        if display_name and "[AFK]" in display_name:
            logger.debug("Skipped AFK Nickname", [("User ID", str(user_id)), ("Name", display_name[:30])])
            return 0

        now = time.time()

        # Insert new record
        cursor = self.execute(
            """INSERT INTO username_history
               (user_id, username, display_name, guild_id, changed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, display_name, guild_id, now)
        )
        new_id = cursor.lastrowid

        # Clean up old records - keep only last 10 per user
        self.execute(
            """DELETE FROM username_history
               WHERE user_id = ? AND id NOT IN (
                   SELECT id FROM username_history
                   WHERE user_id = ?
                   ORDER BY changed_at DESC
                   LIMIT 10
               )""",
            (user_id, user_id)
        )

        return new_id

    def get_username_history(
        self: "DatabaseManager",
        user_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get username history for a user.

        Args:
            user_id: Discord user ID.
            limit: Maximum records to return.

        Returns:
            List of username history records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM username_history
               WHERE user_id = ?
               ORDER BY changed_at DESC
               LIMIT ?""",
            (user_id, limit)
        )
        return [dict(row) for row in rows]

    def get_previous_names(
        self: "DatabaseManager",
        user_id: int,
        limit: int = 5,
    ) -> List[str]:
        """
        Get a simple list of previous usernames/nicknames for display.

        Args:
            user_id: Discord user ID.
            limit: Maximum names to return.

        Returns:
            List of unique previous names, newest first.
        """
        rows = self.fetchall(
            """SELECT username, display_name FROM username_history
               WHERE user_id = ?
               ORDER BY changed_at DESC
               LIMIT ?""",
            (user_id, limit * 2)  # Fetch more to account for duplicates
        )

        # Collect unique names
        seen = set()
        names = []
        for row in rows:
            # Prefer username, fallback to display_name
            name = row["username"] or row["display_name"]
            if name and name not in seen:
                seen.add(name)
                names.append(name)
                if len(names) >= limit:
                    break

        return names

    def has_username_history(self: "DatabaseManager", user_id: int) -> bool:
        """
        Check if a user has any username history.

        Args:
            user_id: Discord user ID.

        Returns:
            True if history exists.
        """
        row = self.fetchone(
            "SELECT 1 FROM username_history WHERE user_id = ? LIMIT 1",
            (user_id,)
        )
        return row is not None

    # =========================================================================
    # Combined History for Display
    # =========================================================================

    def get_combined_history(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        limit: int = 25,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Get combined mute, ban, warn, timeout, and kick history for a user.

        Returns a unified list sorted by timestamp, with type indicators.
        Uses single UNION ALL query for efficiency.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.
            offset: Number of records to skip (for pagination).

        Returns:
            List of history records with 'type' field indicating category.
        """
        # Single UNION ALL query - sorted and paginated in SQL
        rows = self.fetchall(
            """SELECT id, user_id, guild_id, moderator_id, action, reason,
                      duration_seconds, timestamp, 'mute' as type
               FROM mute_history
               WHERE user_id = ? AND guild_id = ?
               UNION ALL
               SELECT id, user_id, guild_id, moderator_id, action, reason,
                      NULL as duration_seconds, timestamp, 'ban' as type
               FROM ban_history
               WHERE user_id = ? AND guild_id = ?
               UNION ALL
               SELECT id, user_id, guild_id, moderator_id, 'warn' as action, reason,
                      NULL as duration_seconds, created_at as timestamp, 'warn' as type
               FROM warnings
               WHERE user_id = ? AND guild_id = ?
               UNION ALL
               SELECT id, user_id, guild_id, moderator_id, action, reason,
                      duration_seconds, timestamp, 'timeout' as type
               FROM timeout_history
               WHERE user_id = ? AND guild_id = ?
               UNION ALL
               SELECT id, user_id, guild_id, moderator_id, 'kick' as action, reason,
                      NULL as duration_seconds, timestamp, 'kick' as type
               FROM kick_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY timestamp DESC
               LIMIT ? OFFSET ?""",
            (user_id, guild_id, user_id, guild_id, user_id, guild_id, user_id, guild_id, user_id, guild_id, limit, offset)
        )

        combined = [dict(row) for row in rows]

        # Log history query
        logger.tree("HISTORY QUERIED", [
            ("User ID", str(user_id)),
            ("Total", str(len(combined))),
        ], emoji="📋")

        return combined

    def get_history_count(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """
        Get total count of history records (mutes + bans + warnings + timeouts + kicks).
        Uses single query with subqueries for efficiency.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Total count.
        """
        row = self.fetchone(
            """SELECT
                (SELECT COUNT(*) FROM mute_history WHERE user_id = ? AND guild_id = ?) +
                (SELECT COUNT(*) FROM ban_history WHERE user_id = ? AND guild_id = ?) +
                (SELECT COUNT(*) FROM warnings WHERE user_id = ? AND guild_id = ?) +
                (SELECT COUNT(*) FROM timeout_history WHERE user_id = ? AND guild_id = ?) +
                (SELECT COUNT(*) FROM kick_history WHERE user_id = ? AND guild_id = ?) as total""",
            (user_id, guild_id, user_id, guild_id, user_id, guild_id, user_id, guild_id, user_id, guild_id)
        )
        return row["total"] if row else 0


__all__ = ["HistoryMixin"]
