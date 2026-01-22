"""
AzabBot - Activity Operations Mixin
===================================

Member activity and message logging operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.config import NY_TZ

if TYPE_CHECKING:
    from .manager import DatabaseManager


class ActivityMixin:
    """Mixin for member activity and message logging operations."""

    # =========================================================================
    # Message Logging
    # =========================================================================

    async def log_message(
        self: "DatabaseManager",
        user_id: int,
        username: str,
        content: str,
        channel_id: int,
        guild_id: int,
    ) -> None:
        """
        Log a message to the database.

        DESIGN: Runs in thread to avoid blocking event loop.
        Content truncated to 500 chars for storage efficiency.
        """
        def _log():
            timestamp = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            truncated = content[:500] if content else ""

            self.execute(
                "INSERT OR REPLACE INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            self.execute(
                """INSERT INTO messages
                   (user_id, content, channel_id, guild_id, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, truncated, channel_id, guild_id, timestamp)
            )
            self.execute(
                "UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?",
                (user_id,)
            )

        await asyncio.to_thread(_log)

    # =========================================================================
    # Member Activity Operations
    # =========================================================================

    def record_member_join(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        join_message_id: Optional[int] = None
    ) -> int:
        """
        Record a member join and return their join count.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            join_message_id: Optional message ID of the join log embed.

        Returns:
            The member's total join count (including this one).
        """
        now = time.time()
        # Insert or update the member activity record
        self.execute(
            """INSERT INTO member_activity (user_id, guild_id, join_count, first_joined_at, last_joined_at, join_message_id)
               VALUES (?, ?, 1, ?, ?, ?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET
                   join_count = join_count + 1,
                   last_joined_at = ?,
                   join_message_id = ?""",
            (user_id, guild_id, now, now, join_message_id, now, join_message_id)
        )
        # Get the updated count
        row = self.fetchone(
            "SELECT join_count FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["join_count"] if row else 1

    def record_member_leave(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """
        Record a member leave and return their leave count.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            The member's total leave count (including this one).
        """
        now = time.time()
        # Insert or update the member activity record
        self.execute(
            """INSERT INTO member_activity (user_id, guild_id, leave_count, last_left_at)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET
                   leave_count = leave_count + 1,
                   last_left_at = ?""",
            (user_id, guild_id, now, now)
        )
        # Get the updated count
        row = self.fetchone(
            "SELECT leave_count FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["leave_count"] if row else 1

    def get_member_activity(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get a member's join/leave activity.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Dict with join_count, leave_count, first_joined_at, last_joined_at, last_left_at
            or None if no record exists.
        """
        row = self.fetchone(
            "SELECT * FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    def get_join_message_id(self: "DatabaseManager", user_id: int, guild_id: int) -> Optional[int]:
        """
        Get the join message ID for a member (without clearing).

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            The join message ID if it exists, or None.
        """
        row = self.fetchone(
            "SELECT join_message_id FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["join_message_id"] if row and row["join_message_id"] else None

    def pop_join_message_id(self: "DatabaseManager", user_id: int, guild_id: int) -> Optional[int]:
        """
        Get and clear the join message ID for a member.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            The join message ID if it exists, or None.
        """
        row = self.fetchone(
            "SELECT join_message_id FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        if row and row["join_message_id"]:
            # Clear the message ID
            self.execute(
                "UPDATE member_activity SET join_message_id = NULL WHERE user_id = ? AND guild_id = ?",
                (user_id, guild_id)
            )
            return row["join_message_id"]
        return None


__all__ = ["ActivityMixin"]
