"""
Database - Snipe Cache Mixin
============================

Snipe cache operations for deleted messages.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


def _safe_json_loads(value: Optional[str], default: Any = None) -> Any:
    """Safely parse JSON, returning default on error."""
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return default if default is not None else []


class SnipeMixin:
    """Mixin for snipe cache operations."""

    def save_snipe(
        self: "DatabaseManager",
        channel_id: int,
        author_id: int,
        author_name: str,
        author_display: str,
        author_avatar: Optional[str],
        content: Optional[str],
        attachment_names: List[str],
        deleted_at: float,
        attachment_urls: Optional[List[Dict[str, Any]]] = None,
        sticker_urls: Optional[List[Dict[str, Any]]] = None,
        message_id: Optional[int] = None,
        attachment_data: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        """
        Save a deleted message to snipe cache.

        Args:
            channel_id: Channel where message was deleted.
            author_id: Author's Discord ID.
            author_name: Author's username.
            author_display: Author's display name.
            author_avatar: Author's avatar URL.
            content: Message content.
            attachment_names: List of attachment filenames (legacy).
            deleted_at: Timestamp when deleted.
            attachment_urls: List of attachment data dicts with url, filename, content_type, size.
            sticker_urls: List of sticker data dicts with name, url.
            message_id: Original message ID (legacy, no longer used).
            attachment_data: List of dicts with filename and base64-encoded file bytes.
        """
        self.execute(
            """INSERT INTO snipe_cache
               (channel_id, message_id, author_id, author_name, author_display, author_avatar, content, attachment_names, attachment_urls, attachment_data, sticker_urls, deleted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                channel_id, message_id, author_id, author_name, author_display, author_avatar, content,
                json.dumps(attachment_names),
                json.dumps(attachment_urls) if attachment_urls else None,
                json.dumps(attachment_data) if attachment_data else None,
                json.dumps(sticker_urls) if sticker_urls else None,
                deleted_at,
            )
        )

        # Keep only 10 messages per channel
        self.execute(
            """DELETE FROM snipe_cache
               WHERE channel_id = ? AND id NOT IN (
                   SELECT id FROM snipe_cache WHERE channel_id = ?
                   ORDER BY deleted_at DESC LIMIT 10
               )""",
            (channel_id, channel_id)
        )

    def get_snipes(
        self: "DatabaseManager",
        channel_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get cached deleted messages for a channel.

        Args:
            channel_id: Channel ID.
            limit: Max messages to return.

        Returns:
            List of snipe data dicts.
        """
        rows = self.fetchall(
            """SELECT message_id, author_id, author_name, author_display, author_avatar, content,
                      attachment_names, attachment_urls, attachment_data, sticker_urls, deleted_at
               FROM snipe_cache
               WHERE channel_id = ?
               ORDER BY deleted_at DESC
               LIMIT ?""",
            (channel_id, limit)
        )

        snipes = []
        for row in rows:
            snipes.append({
                "message_id": row["message_id"],
                "author_id": row["author_id"],
                "author_name": row["author_name"],
                "author_display": row["author_display"],
                "author_avatar": row["author_avatar"],
                "content": row["content"],
                "attachment_names": _safe_json_loads(row["attachment_names"], default=[]),
                "attachment_urls": _safe_json_loads(row["attachment_urls"], default=[]),
                "attachment_data": _safe_json_loads(row["attachment_data"], default=[]),
                "sticker_urls": _safe_json_loads(row["sticker_urls"], default=[]),
                "deleted_at": row["deleted_at"],
            })

        return snipes

    def clear_snipes(
        self: "DatabaseManager",
        channel_id: int,
        user_id: Optional[int] = None
    ) -> int:
        """
        Clear snipe cache for a channel.

        Args:
            channel_id: Channel ID.
            user_id: Optional - only clear messages from this user.

        Returns:
            Number of messages cleared.
        """
        if user_id:
            cursor = self.execute(
                "DELETE FROM snipe_cache WHERE channel_id = ? AND author_id = ?",
                (channel_id, user_id)
            )
        else:
            cursor = self.execute(
                "DELETE FROM snipe_cache WHERE channel_id = ?",
                (channel_id,)
            )

        return cursor.rowcount

    def cleanup_old_snipes(
        self: "DatabaseManager",
        max_age_seconds: int = 600
    ) -> int:
        """
        Clean up snipes older than max age.

        Args:
            max_age_seconds: Max age in seconds (default 10 minutes).

        Returns:
            Number of messages cleaned.
        """
        cutoff = time.time() - max_age_seconds
        cursor = self.execute(
            "DELETE FROM snipe_cache WHERE deleted_at < ?",
            (cutoff,)
        )
        count = cursor.rowcount
        if count > 0:
            logger.debug("Old Snipes Cleaned", [("Count", str(count))])
        return count


__all__ = ["SnipeMixin"]
