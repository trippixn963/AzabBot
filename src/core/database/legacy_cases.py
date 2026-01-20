"""
Database Legacy Case Operations Module
======================================

Legacy case log (per-user) database operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from src.core.logger import logger

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class LegacyCasesMixin:
    """Mixin for legacy case log operations (per-user case_logs table)."""

    def get_case_log(self: "DatabaseManager", user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get case log for a user.

        Args:
            user_id: Discord user ID.

        Returns:
            Case log dict or None if no case exists.
        """
        row = self.fetchone(
            "SELECT * FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        if row:
            return dict(row)
        return None

    def create_case_log(
        self,
        user_id: int,
        case_id: str,
        thread_id: int,
        duration: Optional[str] = None,
        moderator_id: Optional[int] = None,
    ) -> None:
        """
        Create a new case log for a user.

        Args:
            user_id: Discord user ID.
            case_id: Unique 4-character alphanumeric case ID.
            thread_id: Forum thread ID for this case.
            duration: Optional duration string of the first mute.
            moderator_id: Optional moderator ID who issued the first mute.
        """
        now = time.time()
        self.execute(
            """INSERT INTO case_logs
               (user_id, case_id, thread_id, mute_count, created_at, last_mute_at,
                last_mute_duration, last_mute_moderator_id)
               VALUES (?, ?, ?, 1, ?, ?, ?, ?)""",
            (user_id, case_id, thread_id, now, now, duration, moderator_id)
        )

        logger.tree("Case Log Created", [
            ("User ID", str(user_id)),
            ("Case ID", case_id),
            ("Thread ID", str(thread_id)),
        ], emoji="📋")

    def increment_mute_count(
        self,
        user_id: int,
        duration: Optional[str] = None,
        moderator_id: Optional[int] = None,
    ) -> int:
        """
        Increment mute count for a user's case.

        Args:
            user_id: Discord user ID.
            duration: Optional duration string (e.g., "1h", "1d").
            moderator_id: Optional moderator ID who issued the mute.

        Returns:
            New mute count.
        """
        now = time.time()
        self.execute(
            """UPDATE case_logs
               SET mute_count = mute_count + 1,
                   last_mute_at = ?,
                   last_mute_duration = ?,
                   last_mute_moderator_id = ?
               WHERE user_id = ?""",
            (now, duration, moderator_id, user_id)
        )

        row = self.fetchone(
            "SELECT mute_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        new_count = row["mute_count"] if row else 1

        logger.debug("Mute Count Incremented", [
            ("User ID", str(user_id)),
            ("New Count", str(new_count)),
        ])

        return new_count

    def get_last_mute_info(self: "DatabaseManager", user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get last mute info for a user's case.

        Args:
            user_id: Discord user ID.

        Returns:
            Dict with last_mute_at, last_mute_duration, last_mute_moderator_id.
        """
        row = self.fetchone(
            """SELECT last_mute_at, last_mute_duration, last_mute_moderator_id
               FROM case_logs WHERE user_id = ?""",
            (user_id,)
        )
        if row:
            return {
                "last_mute_at": row["last_mute_at"],
                "last_mute_duration": row["last_mute_duration"],
                "last_mute_moderator_id": row["last_mute_moderator_id"],
            }
        return None

    def update_last_unmute(self: "DatabaseManager", user_id: int) -> None:
        """
        Update last unmute timestamp for a user's case.

        Args:
            user_id: Discord user ID.
        """
        now = time.time()
        self.execute(
            "UPDATE case_logs SET last_unmute_at = ? WHERE user_id = ?",
            (now, user_id)
        )

        logger.debug("Last Unmute Updated", [
            ("User ID", str(user_id)),
        ])

    def increment_ban_count(
        self,
        user_id: int,
        moderator_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> int:
        """
        Increment ban count for a user's case.

        Args:
            user_id: Discord user ID.
            moderator_id: Optional moderator ID who issued the ban.
            reason: Optional reason for the ban.

        Returns:
            New ban count.
        """
        now = time.time()
        self.execute(
            """UPDATE case_logs
               SET ban_count = COALESCE(ban_count, 0) + 1,
                   last_ban_at = ?,
                   last_ban_moderator_id = ?,
                   last_ban_reason = ?
               WHERE user_id = ?""",
            (now, moderator_id, reason, user_id)
        )

        row = self.fetchone(
            "SELECT ban_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        new_count = row["ban_count"] if row and row["ban_count"] else 1

        logger.debug("Ban Count Incremented", [
            ("User ID", str(user_id)),
            ("New Count", str(new_count)),
        ])

        return new_count

    def get_last_ban_info(self: "DatabaseManager", user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get last ban info for a user's case.

        Args:
            user_id: Discord user ID.

        Returns:
            Dict with last_ban_at, last_ban_moderator_id, last_ban_reason.
        """
        row = self.fetchone(
            """SELECT last_ban_at, last_ban_moderator_id, last_ban_reason
               FROM case_logs WHERE user_id = ?""",
            (user_id,)
        )
        if row:
            return {
                "last_ban_at": row["last_ban_at"],
                "last_ban_moderator_id": row["last_ban_moderator_id"],
                "last_ban_reason": row["last_ban_reason"],
            }
        return None

    def get_user_ban_count(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """
        Get total number of bans for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID (unused, for API consistency).

        Returns:
            Total ban count.
        """
        row = self.fetchone(
            "SELECT ban_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        return row["ban_count"] if row and row["ban_count"] else 0

    def increment_warn_count(
        self,
        user_id: int,
        moderator_id: Optional[int] = None,
    ) -> int:
        """
        Increment warn count for a user's case.

        Args:
            user_id: Discord user ID.
            moderator_id: Optional moderator ID who issued the warning.

        Returns:
            New warn count.
        """
        now = time.time()
        self.execute(
            """UPDATE case_logs
               SET warn_count = COALESCE(warn_count, 0) + 1,
                   last_warn_at = ?
               WHERE user_id = ?""",
            (now, user_id)
        )

        row = self.fetchone(
            "SELECT warn_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        new_count = row["warn_count"] if row and row["warn_count"] else 1

        logger.debug("Warn Count Incremented", [
            ("User ID", str(user_id)),
            ("New Count", str(new_count)),
        ])

        return new_count

    def get_all_case_logs(self: "DatabaseManager") -> List[Dict[str, Any]]:
        """
        Get all case logs.

        Returns:
            List of all case log dicts.
        """
        rows = self.fetchall("SELECT * FROM case_logs ORDER BY case_id")
        return [dict(row) for row in rows]

    def set_profile_message_id(self: "DatabaseManager", user_id: int, message_id: int) -> None:
        """
        Set the profile message ID for a case.

        Args:
            user_id: Discord user ID.
            message_id: The message ID of the pinned profile.
        """
        self.execute(
            "UPDATE case_logs SET profile_message_id = ? WHERE user_id = ?",
            (message_id, user_id)
        )

        logger.debug("Profile Message ID Set", [
            ("User ID", str(user_id)),
            ("Message ID", str(message_id)),
        ])


__all__ = ["LegacyCasesMixin"]
