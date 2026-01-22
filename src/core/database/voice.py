"""
AzabBot - Voice Activity Mixin
==============================

Voice activity tracking operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, List

from src.core.config import NY_TZ
from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


class VoiceMixin:
    """Mixin for voice activity operations."""

    def save_voice_activity(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        channel_id: int,
        channel_name: str,
        action: str,
    ) -> None:
        """
        Save a voice activity event (join/leave).

        Args:
            user_id: Discord user ID.
            guild_id: Discord guild ID.
            channel_id: Voice channel ID.
            channel_name: Voice channel name.
            action: 'join' or 'leave'.
        """
        self.execute(
            """INSERT INTO voice_activity
               (user_id, guild_id, channel_id, channel_name, action, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, channel_id, channel_name, action, datetime.now(NY_TZ).timestamp())
        )

    def get_recent_voice_activity(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        limit: int = 10,
        max_age_seconds: int = 3600,
    ) -> list:
        """
        Get recent voice activity for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Discord guild ID.
            limit: Max records to return.
            max_age_seconds: Only return activity within this time window.

        Returns:
            List of voice activity records (newest first).
        """
        cutoff = datetime.now(NY_TZ).timestamp() - max_age_seconds
        rows = self.fetchall(
            """SELECT channel_id, channel_name, action, timestamp
               FROM voice_activity
               WHERE user_id = ? AND guild_id = ? AND timestamp > ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, guild_id, cutoff, limit)
        )
        return [dict(row) for row in rows] if rows else []

    def cleanup_old_voice_activity(
        self: "DatabaseManager",
        max_age_seconds: int = 86400
    ) -> int:
        """
        Clean up old voice activity records.

        Args:
            max_age_seconds: Delete records older than this (default 24h).

        Returns:
            Number of records deleted.
        """
        cutoff = datetime.now(NY_TZ).timestamp() - max_age_seconds
        cursor = self.execute(
            "DELETE FROM voice_activity WHERE timestamp < ?",
            (cutoff,)
        )
        count = cursor.rowcount if cursor else 0
        if count > 0:
            logger.debug("Old Voice Activity Cleaned", [("Count", str(count))])
        return count


__all__ = ["VoiceMixin"]
