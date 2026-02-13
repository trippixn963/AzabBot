"""
AzabBot - User Snapshots Database Mixin
=======================================

Handles user snapshot caching for banned/left users.
Preserves user profile data (nickname, roles, avatar) even after they leave.
Activity data comes from SyriaBot which retains data for inactive users.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import sqlite3
import time
from typing import TYPE_CHECKING, Optional, List, Dict, Any

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class SnapshotsMixin:
    """Database mixin for user snapshot operations."""

    # =========================================================================
    # Snapshot Creation/Update
    # =========================================================================

    def save_user_snapshot(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        username: str,
        display_name: str,
        nickname: Optional[str],
        avatar_url: Optional[str],
        roles: List[Dict[str, Any]],
        joined_at: Optional[float],
        account_created_at: Optional[float],
        reason: str,
    ) -> bool:
        """
        Save or update a user snapshot (profile data only).

        Args:
            user_id: Discord user ID
            guild_id: Guild ID
            username: Discord username
            display_name: Display name
            nickname: Server nickname (if any)
            avatar_url: Avatar URL
            roles: List of role dicts with id, name, color, position
            joined_at: Unix timestamp of when they joined
            account_created_at: Unix timestamp of account creation
            reason: Why snapshot was taken (ban, kick, leave, mute, lookup)

        Returns:
            True if saved successfully
        """
        now = time.time()
        roles_json = json.dumps(roles) if roles else "[]"

        try:
            self.execute(
                """
                INSERT INTO user_snapshots
                    (user_id, guild_id, username, display_name, nickname,
                     avatar_url, roles, joined_at, account_created_at,
                     snapshot_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, guild_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    nickname = excluded.nickname,
                    avatar_url = excluded.avatar_url,
                    roles = excluded.roles,
                    joined_at = COALESCE(excluded.joined_at, user_snapshots.joined_at),
                    account_created_at = COALESCE(excluded.account_created_at, user_snapshots.account_created_at),
                    snapshot_reason = excluded.snapshot_reason,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id, guild_id, username, display_name, nickname,
                    avatar_url, roles_json, joined_at, account_created_at,
                    reason, now, now
                )
            )
            return True
        except sqlite3.Error:
            # Database error during snapshot save
            return False

    # =========================================================================
    # Snapshot Retrieval
    # =========================================================================

    def get_user_snapshot(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get a user's cached snapshot.

        Args:
            user_id: Discord user ID
            guild_id: Guild ID

        Returns:
            Dict with user data or None if not found
        """
        row = self.fetchone(
            """
            SELECT user_id, guild_id, username, display_name, nickname,
                   avatar_url, roles, joined_at, account_created_at,
                   snapshot_reason, created_at, updated_at
            FROM user_snapshots
            WHERE user_id = ? AND guild_id = ?
            """,
            (user_id, guild_id)
        )

        if not row:
            return None

        # Parse roles JSON
        roles = []
        try:
            roles = json.loads(row["roles"]) if row["roles"] else []
        except (json.JSONDecodeError, TypeError):
            pass

        return {
            "user_id": row["user_id"],
            "guild_id": row["guild_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "nickname": row["nickname"],
            "avatar_url": row["avatar_url"],
            "roles": roles,
            "joined_at": row["joined_at"],
            "account_created_at": row["account_created_at"],
            "snapshot_reason": row["snapshot_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_snapshots_by_reason(
        self: "DatabaseManager",
        guild_id: int,
        reason: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get all snapshots with a specific reason (e.g., 'ban', 'leave').

        Args:
            guild_id: Guild ID
            reason: Snapshot reason to filter by
            limit: Max results

        Returns:
            List of snapshot dicts
        """
        rows = self.fetchall(
            """
            SELECT user_id, guild_id, username, display_name, nickname,
                   avatar_url, roles, joined_at, account_created_at,
                   snapshot_reason, created_at, updated_at
            FROM user_snapshots
            WHERE guild_id = ? AND snapshot_reason = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (guild_id, reason, limit)
        )

        results = []
        for row in rows:
            roles = []
            try:
                roles = json.loads(row["roles"]) if row["roles"] else []
            except (json.JSONDecodeError, TypeError):
                pass

            results.append({
                "user_id": row["user_id"],
                "guild_id": row["guild_id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "nickname": row["nickname"],
                "avatar_url": row["avatar_url"],
                "roles": roles,
                "joined_at": row["joined_at"],
                "account_created_at": row["account_created_at"],
                "snapshot_reason": row["snapshot_reason"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })

        return results

    # =========================================================================
    # Snapshot Deletion
    # =========================================================================

    def delete_user_snapshot(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
    ) -> bool:
        """
        Delete a user's snapshot (e.g., when they rejoin and we have fresh data).

        Args:
            user_id: Discord user ID
            guild_id: Guild ID

        Returns:
            True if deleted
        """
        cursor = self.execute(
            "DELETE FROM user_snapshots WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return cursor.rowcount > 0

    def cleanup_old_snapshots(
        self: "DatabaseManager",
        guild_id: int,
        days_old: int = 365,
    ) -> int:
        """
        Delete snapshots older than specified days.
        Keeps snapshots for users with moderation history.

        Args:
            guild_id: Guild ID
            days_old: Delete snapshots older than this

        Returns:
            Number of deleted snapshots
        """
        cutoff = time.time() - (days_old * 86400)

        cursor = self.execute(
            """
            DELETE FROM user_snapshots
            WHERE guild_id = ?
              AND updated_at < ?
              AND user_id NOT IN (
                  SELECT DISTINCT user_id FROM cases WHERE guild_id = ?
              )
            """,
            (guild_id, cutoff, guild_id)
        )
        return cursor.rowcount

    # =========================================================================
    # Stats
    # =========================================================================

    def get_snapshot_stats(
        self: "DatabaseManager",
        guild_id: int,
    ) -> Dict[str, int]:
        """
        Get snapshot statistics for a guild.

        Returns:
            Dict with counts by reason
        """
        rows = self.fetchall(
            """
            SELECT snapshot_reason, COUNT(*) as count
            FROM user_snapshots
            WHERE guild_id = ?
            GROUP BY snapshot_reason
            """,
            (guild_id,)
        )

        stats = {"total": 0}
        for row in rows:
            stats[row["snapshot_reason"]] = row["count"]
            stats["total"] += row["count"]

        return stats


__all__ = ["SnapshotsMixin"]
