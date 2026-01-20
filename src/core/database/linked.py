"""
Database - Linked Messages Mixin
================================

Linked messages operations for auto-deletion on leave.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


class LinkedMixin:
    """Mixin for linked messages operations."""

    def save_linked_message(
        self: "DatabaseManager",
        message_id: int,
        channel_id: int,
        member_id: int,
        guild_id: int,
        linked_by: int,
    ) -> bool:
        """
        Link a message to a member for auto-deletion on leave.

        Args:
            message_id: Discord message ID.
            channel_id: Channel where message is.
            member_id: Member to link the message to.
            guild_id: Guild ID.
            linked_by: Moderator who created the link.

        Returns:
            True if saved, False if already linked.
        """
        try:
            self.execute(
                """INSERT INTO linked_messages
                   (message_id, channel_id, member_id, guild_id, linked_by, linked_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (message_id, channel_id, member_id, guild_id, linked_by, time.time())
            )
            logger.debug("Linked Message Saved", [
                ("Message ID", str(message_id)),
                ("Member ID", str(member_id)),
            ])
            return True
        except sqlite3.IntegrityError:
            return False  # Already linked

    def get_linked_messages_by_member(
        self: "DatabaseManager",
        member_id: int,
        guild_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Get all messages linked to a member.

        Args:
            member_id: Member ID.
            guild_id: Guild ID.

        Returns:
            List of linked message records.
        """
        rows = self.fetchall(
            """SELECT message_id, channel_id, linked_by, linked_at
               FROM linked_messages
               WHERE member_id = ? AND guild_id = ?""",
            (member_id, guild_id)
        )
        return [dict(row) for row in rows]

    def delete_linked_message(
        self: "DatabaseManager",
        message_id: int,
        channel_id: int
    ) -> bool:
        """
        Remove a linked message record.

        Args:
            message_id: Discord message ID.
            channel_id: Channel ID.

        Returns:
            True if deleted, False if not found.
        """
        cursor = self.execute(
            "DELETE FROM linked_messages WHERE message_id = ? AND channel_id = ?",
            (message_id, channel_id)
        )
        if cursor.rowcount > 0:
            logger.debug("Linked Message Deleted", [("Message ID", str(message_id))])
        return cursor.rowcount > 0

    def delete_linked_messages_by_member(
        self: "DatabaseManager",
        member_id: int,
        guild_id: int
    ) -> int:
        """
        Remove all linked messages for a member.

        Args:
            member_id: Member ID.
            guild_id: Guild ID.

        Returns:
            Number of records deleted.
        """
        cursor = self.execute(
            "DELETE FROM linked_messages WHERE member_id = ? AND guild_id = ?",
            (member_id, guild_id)
        )
        count = cursor.rowcount
        if count > 0:
            logger.debug("Linked Messages Cleared", [
                ("Member ID", str(member_id)),
                ("Count", str(count)),
            ])
        return count

    def get_linked_message(
        self: "DatabaseManager",
        message_id: int,
        channel_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get a linked message record.

        Args:
            message_id: Discord message ID.
            channel_id: Channel ID.

        Returns:
            Linked message record or None.
        """
        row = self.fetchone(
            """SELECT message_id, channel_id, member_id, guild_id, linked_by, linked_at
               FROM linked_messages
               WHERE message_id = ? AND channel_id = ?""",
            (message_id, channel_id)
        )
        return dict(row) if row else None


__all__ = ["LinkedMixin"]
