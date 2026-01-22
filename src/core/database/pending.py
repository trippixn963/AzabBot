"""
AzabBot - Pending Reasons Mixin
===============================

Pending reason operations for case management.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Dict, List, Optional

from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


class PendingMixin:
    """Mixin for pending reason operations."""

    def create_pending_reason(
        self: "DatabaseManager",
        thread_id: int,
        warning_message_id: int,
        embed_message_id: int,
        moderator_id: int,
        target_user_id: int,
        action_type: str,
    ) -> int:
        """
        Create a pending reason request.

        Args:
            thread_id: Case thread ID.
            warning_message_id: ID of the warning message to delete when resolved.
            embed_message_id: ID of the embed to update with reason.
            moderator_id: Moderator who needs to provide reason.
            target_user_id: User the action was taken against.
            action_type: Type of action (mute, ban, etc).

        Returns:
            ID of the created pending reason.
        """
        cursor = self.execute(
            """
            INSERT INTO pending_reasons
            (thread_id, warning_message_id, embed_message_id, moderator_id, target_user_id, action_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (thread_id, warning_message_id, embed_message_id, moderator_id, target_user_id, action_type, time.time())
        )
        return cursor.lastrowid or 0

    def get_pending_reason_by_thread(
        self: "DatabaseManager",
        thread_id: int,
        moderator_id: int
    ) -> Optional[Dict]:
        """
        Get pending reason for a thread and moderator.

        Args:
            thread_id: Case thread ID.
            moderator_id: Moderator ID.

        Returns:
            Pending reason record or None.
        """
        row = self.fetchone(
            """
            SELECT * FROM pending_reasons
            WHERE thread_id = ? AND moderator_id = ? AND owner_notified = 0
            ORDER BY created_at DESC LIMIT 1
            """,
            (thread_id, moderator_id)
        )
        return dict(row) if row else None

    def get_expired_pending_reasons(
        self: "DatabaseManager",
        max_age_seconds: int = 3600
    ) -> List[Dict]:
        """
        Get pending reasons older than max_age_seconds that haven't been resolved.

        Args:
            max_age_seconds: Maximum age in seconds (default 1 hour).

        Returns:
            List of expired pending reason records.
        """
        cutoff = time.time() - max_age_seconds
        rows = self.fetchall(
            """
            SELECT * FROM pending_reasons
            WHERE created_at < ? AND owner_notified = 0
            """,
            (cutoff,)
        )
        return [dict(row) for row in rows]

    def mark_pending_reason_notified(self: "DatabaseManager", pending_id: int) -> None:
        """Mark a pending reason as owner notified."""
        self.execute(
            "UPDATE pending_reasons SET owner_notified = 1 WHERE id = ?",
            (pending_id,)
        )
        logger.debug("Pending Reason Notified", [("ID", str(pending_id))])

    def delete_pending_reason(self: "DatabaseManager", pending_id: int) -> None:
        """Delete a pending reason (when resolved)."""
        self.execute(
            "DELETE FROM pending_reasons WHERE id = ?",
            (pending_id,)
        )
        logger.debug("Pending Reason Deleted", [("ID", str(pending_id))])

    def delete_pending_reasons_for_thread(
        self: "DatabaseManager",
        thread_id: int,
        moderator_id: int
    ) -> None:
        """Delete all pending reasons for a thread and moderator."""
        self.execute(
            "DELETE FROM pending_reasons WHERE thread_id = ? AND moderator_id = ?",
            (thread_id, moderator_id)
        )
        logger.debug("Pending Reasons Cleared", [
            ("Thread ID", str(thread_id)),
            ("Moderator", str(moderator_id)),
        ])

    def cleanup_old_pending_reasons(
        self: "DatabaseManager",
        max_age_seconds: int = 86400
    ) -> int:
        """
        Delete old pending reasons that have been notified.

        Args:
            max_age_seconds: Maximum age in seconds (default 24 hours).

        Returns:
            Number of records deleted.
        """
        cutoff = time.time() - max_age_seconds
        cursor = self.execute(
            "DELETE FROM pending_reasons WHERE owner_notified = 1 AND created_at < ?",
            (cutoff,)
        )
        count = cursor.rowcount
        if count > 0:
            logger.debug("Old Pending Reasons Cleaned", [("Count", str(count))])
        return count


__all__ = ["PendingMixin"]
