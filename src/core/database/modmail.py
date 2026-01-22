"""
AzabBot - Modmail Mixin
=======================

Modmail operations for banned user communication.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Dict, Optional

from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


class ModmailMixin:
    """Mixin for modmail operations."""

    def create_modmail(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        thread_id: int,
    ) -> None:
        """
        Create a modmail entry for a banned user.

        Args:
            user_id: Discord user ID (banned user).
            guild_id: Guild ID they're banned from.
            thread_id: Forum thread ID for this modmail.
        """
        now = time.time()
        self.execute(
            """
            INSERT OR REPLACE INTO modmail
            (user_id, guild_id, thread_id, status, created_at)
            VALUES (?, ?, ?, 'open', ?)
            """,
            (user_id, guild_id, thread_id, now)
        )

        logger.tree("Modmail Created", [
            ("User ID", str(user_id)),
            ("Thread ID", str(thread_id)),
        ], emoji="📬")

    def get_modmail_by_user(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int
    ) -> Optional[Dict]:
        """
        Get modmail entry for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Modmail record dict or None.
        """
        result = self.fetchone(
            "SELECT * FROM modmail WHERE user_id = ? AND guild_id = ? AND status = 'open'",
            (user_id, guild_id)
        )
        return dict(result) if result else None

    def get_modmail_by_thread(
        self: "DatabaseManager",
        thread_id: int
    ) -> Optional[Dict]:
        """
        Get modmail entry by thread ID.

        Args:
            thread_id: Thread ID.

        Returns:
            Modmail record dict or None.
        """
        result = self.fetchone(
            "SELECT * FROM modmail WHERE thread_id = ?",
            (thread_id,)
        )
        return dict(result) if result else None

    def close_modmail(
        self: "DatabaseManager",
        thread_id: int,
        closed_by: int
    ) -> bool:
        """
        Close a modmail thread.

        Args:
            thread_id: Thread ID.
            closed_by: Staff member who closed it.

        Returns:
            True if updated.
        """
        now = time.time()
        cursor = self.execute(
            """
            UPDATE modmail
            SET status = 'closed', closed_at = ?, closed_by = ?
            WHERE thread_id = ?
            """,
            (now, closed_by, thread_id)
        )
        if cursor.rowcount > 0:
            logger.tree("Modmail Closed", [
                ("Thread ID", str(thread_id)),
                ("Closed By", str(closed_by)),
            ], emoji="📪")
        return cursor.rowcount > 0

    def reopen_modmail(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int
    ) -> bool:
        """
        Reopen a closed modmail.

        Args:
            user_id: User ID.
            guild_id: Guild ID.

        Returns:
            True if updated.
        """
        cursor = self.execute(
            """
            UPDATE modmail
            SET status = 'open', closed_at = NULL, closed_by = NULL
            WHERE user_id = ? AND guild_id = ?
            """,
            (user_id, guild_id)
        )
        if cursor.rowcount > 0:
            logger.debug("Modmail Reopened", [
                ("User ID", str(user_id)),
            ])
        return cursor.rowcount > 0


__all__ = ["ModmailMixin"]
