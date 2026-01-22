"""
Database - Mod Tracker Operations Mixin
=======================================

Moderator tracking database operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


class ModTrackerMixin:
    """Mixin for mod tracker database operations."""

    def get_tracked_mod(self: "DatabaseManager", mod_id: int) -> Optional[Dict[str, Any]]:
        """
        Get tracked mod info.

        Args:
            mod_id: Discord user ID of the mod.

        Returns:
            Dict with mod tracker info or None if not tracked.
        """
        row = self.fetchone(
            "SELECT * FROM mod_tracker WHERE mod_id = ?",
            (mod_id,)
        )
        return dict(row) if row else None

    def add_tracked_mod(
        self: "DatabaseManager",
        mod_id: int,
        thread_id: int,
        display_name: str,
        username: str,
        avatar_hash: Optional[str] = None,
    ) -> None:
        """
        Add a mod to the tracker.

        Args:
            mod_id: Discord user ID.
            thread_id: Forum thread ID for their activity log.
            display_name: Current display name.
            username: Current username.
            avatar_hash: Current avatar hash for change detection.
        """
        now = time.time()
        self.execute(
            """INSERT OR REPLACE INTO mod_tracker
               (mod_id, thread_id, display_name, avatar_hash, username, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (mod_id, thread_id, display_name, avatar_hash, username, now)
        )

        logger.debug("Tracked Mod Added", [
            ("Mod ID", str(mod_id)),
            ("Thread ID", str(thread_id)),
        ])

    def remove_tracked_mod(self: "DatabaseManager", mod_id: int) -> bool:
        """
        Remove a mod from the tracker.

        Args:
            mod_id: Discord user ID.

        Returns:
            True if mod was removed, False if not found.
        """
        row = self.fetchone(
            "SELECT mod_id FROM mod_tracker WHERE mod_id = ?",
            (mod_id,)
        )
        if row:
            self.execute("DELETE FROM mod_tracker WHERE mod_id = ?", (mod_id,))
            logger.debug("Tracked Mod Removed", [
                ("Mod ID", str(mod_id)),
            ])
            return True
        return False

    def get_all_tracked_mods(self: "DatabaseManager") -> List[Dict[str, Any]]:
        """
        Get all tracked mods.

        Returns:
            List of all tracked mod dicts.
        """
        rows = self.fetchall("SELECT * FROM mod_tracker")
        return [dict(row) for row in rows]

    def update_tracked_mod_thread(self: "DatabaseManager", mod_id: int, thread_id: int) -> None:
        """Update the thread ID for a tracked mod."""
        self.execute(
            "UPDATE mod_tracker SET thread_id = ? WHERE mod_id = ?",
            (thread_id, mod_id)
        )

    def update_mod_info(
        self: "DatabaseManager",
        mod_id: int,
        display_name: Optional[str] = None,
        username: Optional[str] = None,
        avatar_hash: Optional[str] = None,
    ) -> None:
        """
        Update stored mod info for change detection.

        Args:
            mod_id: Discord user ID.
            display_name: New display name (if changed).
            username: New username (if changed).
            avatar_hash: New avatar hash (if changed).
        """
        updates = []
        params = []

        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
        if username is not None:
            updates.append("username = ?")
            params.append(username)
        if avatar_hash is not None:
            updates.append("avatar_hash = ?")
            params.append(avatar_hash)

        if updates:
            params.append(mod_id)
            self.execute(
                f"UPDATE mod_tracker SET {', '.join(updates)} WHERE mod_id = ?",
                tuple(params)
            )
            logger.debug("Mod Info Updated", [
                ("Mod ID", str(mod_id)),
                ("Fields", ", ".join(updates)),
            ])

    def increment_mod_action_count(self: "DatabaseManager", mod_id: int) -> int:
        """
        Increment the action count for a mod and update last action time.

        Args:
            mod_id: Discord user ID.

        Returns:
            New action count.
        """
        now = time.time()
        self.execute(
            """UPDATE mod_tracker
               SET action_count = COALESCE(action_count, 0) + 1,
                   last_action_at = ?
               WHERE mod_id = ?""",
            (now, mod_id)
        )
        row = self.fetchone(
            "SELECT action_count FROM mod_tracker WHERE mod_id = ?",
            (mod_id,)
        )
        return row["action_count"] if row else 0

    def get_mod_action_count(self: "DatabaseManager", mod_id: int) -> int:
        """
        Get the action count for a mod.

        Args:
            mod_id: Discord user ID.

        Returns:
            Action count (0 if not found).
        """
        row = self.fetchone(
            "SELECT action_count FROM mod_tracker WHERE mod_id = ?",
            (mod_id,)
        )
        return row["action_count"] if row and row["action_count"] else 0

    def increment_hourly_activity(self: "DatabaseManager", mod_id: int, hour: int) -> None:
        """
        Increment the hourly activity count for a mod.

        Args:
            mod_id: Discord user ID.
            hour: Hour of day (0-23).
        """
        self.execute(
            """INSERT INTO mod_hourly_activity (mod_id, hour, count)
               VALUES (?, ?, 1)
               ON CONFLICT(mod_id, hour) DO UPDATE SET count = count + 1""",
            (mod_id, hour)
        )

        logger.debug("Hourly Activity Incremented", [
            ("Mod ID", str(mod_id)),
            ("Hour", str(hour)),
        ])

    def get_peak_hours(self: "DatabaseManager", mod_id: int, top_n: int = 3) -> list:
        """
        Get the peak activity hours for a mod.

        Args:
            mod_id: Discord user ID.
            top_n: Number of top hours to return.

        Returns:
            List of tuples (hour, count) sorted by count descending.
        """
        rows = self.fetchall(
            """SELECT hour, count FROM mod_hourly_activity
               WHERE mod_id = ? AND count > 0
               ORDER BY count DESC
               LIMIT ?""",
            (mod_id, top_n)
        )
        return [(row["hour"], row["count"]) for row in rows]


__all__ = ["ModTrackerMixin"]
