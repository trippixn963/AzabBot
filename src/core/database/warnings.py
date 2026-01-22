"""
AzabBot - Database Warning Operations Module
============================================

Warning database operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from src.core.logger import logger

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class WarningsMixin:
    """Mixin for warning-related database operations."""

    # Warnings older than this many days don't count toward active count
    WARNING_DECAY_DAYS = 30

    def add_warning(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> int:
        """
        Add a warning to the database.

        Args:
            user_id: Discord user ID being warned.
            guild_id: Guild where warning was issued.
            moderator_id: Moderator who issued warning.
            reason: Optional reason for warning.
            evidence: Optional evidence URL/text.

        Returns:
            Row ID of the warning record.
        """
        now = time.time()

        cursor = self.execute(
            """INSERT INTO warnings
               (user_id, guild_id, moderator_id, reason, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, moderator_id, reason, evidence, now)
        )

        logger.tree("Warning Added", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
            ("Reason", (reason or "None")[:50]),
        ], emoji="⚠️")

        return cursor.lastrowid

    def get_user_warn_count(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """
        Get total number of warnings for a user in a guild (all time).

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Total warning count.
        """
        row = self.fetchone(
            "SELECT COUNT(*) as count FROM warnings WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["count"] if row else 0

    def get_active_warn_count(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """
        Get number of active (non-expired) warnings for a user.

        Warnings older than WARNING_DECAY_DAYS are considered expired
        and don't count toward the active total.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Active warning count.
        """
        decay_cutoff = time.time() - (self.WARNING_DECAY_DAYS * 86400)
        row = self.fetchone(
            """SELECT COUNT(*) as count FROM warnings
               WHERE user_id = ? AND guild_id = ? AND created_at >= ?""",
            (user_id, guild_id, decay_cutoff)
        )
        return row["count"] if row else 0

    def get_warn_counts(self: "DatabaseManager", user_id: int, guild_id: int) -> tuple:
        """
        Get both active and total warning counts for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Tuple of (active_count, total_count).
        """
        total = self.get_user_warn_count(user_id, guild_id)
        active = self.get_active_warn_count(user_id, guild_id)
        return (active, total)

    def get_user_warnings(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Get all warnings for a user in a guild.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum number of warnings to return.

        Returns:
            List of warning records.
        """
        rows = self.fetchall(
            """SELECT id, user_id, guild_id, moderator_id, reason, evidence, created_at
               FROM warnings
               WHERE user_id = ? AND guild_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]


__all__ = ["WarningsMixin"]
