"""
AzabBot - Database Mute Operations Module
=========================================

Prisoner and mute-related database operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
import sqlite3
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from src.core.logger import logger
from src.core.database.models import MuteRecord
from src.core.config import NY_TZ
from src.utils.metrics import metrics

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class MutesMixin:
    """Mixin for mute-related database operations."""

    # Prisoner Operations
    # =========================================================================

    async def record_mute(
        self,
        user_id: int,
        username: str,
        reason: str,
        muted_by: Optional[str] = None,
        trigger_message: Optional[str] = None,
    ) -> None:
        """
        Record a new mute event.

        DESIGN: Deactivates previous mutes before recording new one.
        This ensures only one active mute per user.
        """
        def _record():
            timestamp = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S")

            # Deactivate previous mutes
            self.execute(
                "UPDATE prisoner_history SET is_active = 0 WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )

            # Insert new mute
            self.execute(
                """INSERT INTO prisoner_history
                   (user_id, username, mute_reason, muted_by, trigger_message, muted_at, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (user_id, username, reason, muted_by, trigger_message, timestamp)
            )

            # Update user status
            self.execute(
                "UPDATE users SET is_imprisoned = 1 WHERE user_id = ?",
                (user_id,)
            )

            logger.tree("Mute Recorded", [
                ("User", username),
                ("Reason", reason[:50] if reason else "Unknown"),
            ], emoji="🔒")

        await asyncio.to_thread(_record)

    async def record_unmute(self: "DatabaseManager", user_id: int, unmuted_by: Optional[str] = None) -> None:
        """
        Record unmute event.

        DESIGN: Calculates duration automatically from muted_at timestamp.
        """
        def _record():
            timestamp = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S")

            self.execute(
                """UPDATE prisoner_history SET
                   unmuted_at = ?,
                   unmuted_by = ?,
                   is_active = 0,
                   duration_minutes = ABS(ROUND((JULIANDAY(?) - JULIANDAY(muted_at)) * 24 * 60))
                   WHERE user_id = ? AND is_active = 1""",
                (timestamp, unmuted_by, timestamp, user_id)
            )

            self.execute(
                "UPDATE users SET is_imprisoned = 0 WHERE user_id = ?",
                (user_id,)
            )

            logger.tree("Unmute Recorded", [
                ("User ID", str(user_id)),
            ], emoji="🔓")

        await asyncio.to_thread(_record)

    async def get_current_mute_duration(self: "DatabaseManager", user_id: int) -> int:
        """
        Get current mute duration in minutes.

        Returns:
            Duration in minutes, or 0 if not muted
        """
        def _get():
            row = self.fetchone(
                """SELECT ABS(ROUND((JULIANDAY('now') - JULIANDAY(muted_at)) * 24 * 60)) as duration
                   FROM prisoner_history WHERE user_id = ? AND is_active = 1""",
                (user_id,)
            )
            return row["duration"] if row and row["duration"] else 0

        return await asyncio.to_thread(_get)

    async def get_prisoner_stats(self: "DatabaseManager", user_id: int) -> Dict[str, Any]:
        """
        Get comprehensive prisoner stats in a single optimized query.
        Uses TTL-based caching (60 seconds) to avoid repeated expensive queries.

        Returns:
            Dict with total_mutes, total_minutes, last_mute, etc.
        """
        now = time.time()

        # Check cache first (with lock)
        async with self._prisoner_stats_lock:
            if user_id in self._prisoner_stats_cache:
                cached_stats, cached_at = self._prisoner_stats_cache[user_id]
                if now - cached_at < self._prisoner_stats_ttl:
                    return cached_stats

        def _get():
            with metrics.timer("db.get_prisoner_stats"):
                # Single query with all stats using subqueries
                row = self.fetchone(
                    """SELECT
                        (SELECT COUNT(*) FROM prisoner_history WHERE user_id = ?) as total_mutes,
                        (SELECT COALESCE(SUM(duration_minutes), 0) FROM prisoner_history WHERE user_id = ?) as total_minutes,
                        (SELECT MAX(muted_at) FROM prisoner_history WHERE user_id = ?) as last_mute,
                        (SELECT COUNT(DISTINCT mute_reason) FROM prisoner_history WHERE user_id = ?) as unique_reasons,
                        (SELECT mute_reason FROM prisoner_history WHERE user_id = ? AND is_active = 1 LIMIT 1) as current_reason,
                        (SELECT GROUP_CONCAT(mute_reason || ':' || cnt) FROM
                            (SELECT mute_reason, COUNT(*) as cnt FROM prisoner_history
                             WHERE user_id = ? GROUP BY mute_reason ORDER BY cnt DESC)
                        ) as reason_breakdown
                    """,
                    (user_id, user_id, user_id, user_id, user_id, user_id)
                )

                # Parse reason breakdown from concatenated string
                reason_counts = {}
                if row["reason_breakdown"]:
                    for item in row["reason_breakdown"].split(","):
                        if ":" in item:
                            reason, count = item.rsplit(":", 1)
                            reason_counts[reason] = int(count)

                return {
                    "total_mutes": row["total_mutes"] or 0,
                    "total_minutes": row["total_minutes"] or 0,
                    "last_mute": row["last_mute"],
                    "unique_reasons": row["unique_reasons"] or 0,
                    "reason_counts": reason_counts,
                    "is_currently_muted": row["current_reason"] is not None,
                    "current_reason": row["current_reason"],
                }

        stats = await asyncio.to_thread(_get)

        # Cache the result (with lock)
        async with self._prisoner_stats_lock:
            self._prisoner_stats_cache[user_id] = (stats, now)

            # Evict old cache entries (keep max 1000)
            if len(self._prisoner_stats_cache) > 1000:
                try:
                    oldest_key = min(self._prisoner_stats_cache.keys(),
                                   key=lambda k: self._prisoner_stats_cache[k][1])
                    del self._prisoner_stats_cache[oldest_key]
                except (KeyError, ValueError):
                    pass  # Entry already removed by another coroutine

        return stats

    async def get_current_mute_session_id(self: "DatabaseManager", user_id: int) -> Optional[int]:
        """Get current active mute session ID."""
        def _get():
            row = self.fetchone(
                "SELECT id FROM prisoner_history WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            return row["id"] if row else None

        return await asyncio.to_thread(_get)

    # =========================================================================
    # Moderation Mute Operations
    # =========================================================================

    def add_mute(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> int:
        """
        Add a mute record to the database.

        DESIGN:
            Uses INSERT OR REPLACE to handle re-muting.
            Stores expiration time for scheduler to auto-unmute.
            Logs to mute_history for modlog.

        Args:
            user_id: Discord user ID being muted.
            guild_id: Guild where mute occurred.
            moderator_id: Moderator who issued mute.
            reason: Optional reason for mute.
            duration_seconds: Duration in seconds, None for permanent.

        Returns:
            Row ID of the mute record.
        """
        now = time.time()
        expires_at = now + duration_seconds if duration_seconds else None

        # Insert/update active mute
        cursor = self.execute(
            """INSERT OR REPLACE INTO active_mutes
               (user_id, guild_id, moderator_id, reason, muted_at, expires_at, unmuted)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (user_id, guild_id, moderator_id, reason, now, expires_at)
        )

        # Log to history
        self.execute(
            """INSERT INTO mute_history
               (user_id, guild_id, moderator_id, action, reason, duration_seconds, timestamp)
               VALUES (?, ?, ?, 'mute', ?, ?, ?)""",
            (user_id, guild_id, moderator_id, reason, duration_seconds, now)
        )

        logger.tree("Moderation Mute Added", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
            ("Duration", f"{duration_seconds}s" if duration_seconds else "Permanent"),
            ("Reason", (reason or "None")[:50]),
        ], emoji="🔇")

        return cursor.lastrowid

    def remove_mute(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Remove a mute (unmute a user).

        Args:
            user_id: Discord user ID being unmuted.
            guild_id: Guild where unmute occurred.
            moderator_id: Moderator who issued unmute.
            reason: Optional reason for unmute.

        Returns:
            True if user was muted and is now unmuted, False if wasn't muted.
        """
        now = time.time()

        # Check if user is muted
        row = self.fetchone(
            "SELECT id FROM active_mutes WHERE user_id = ? AND guild_id = ? AND unmuted = 0",
            (user_id, guild_id)
        )

        if not row:
            return False

        # Mark as unmuted
        self.execute(
            "UPDATE active_mutes SET unmuted = 1 WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )

        # Log to history
        self.execute(
            """INSERT INTO mute_history
               (user_id, guild_id, moderator_id, action, reason, duration_seconds, timestamp)
               VALUES (?, ?, ?, 'unmute', ?, NULL, ?)""",
            (user_id, guild_id, moderator_id, reason, now)
        )

        logger.tree("Moderation Mute Removed", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
            ("Reason", (reason or "None")[:50]),
        ], emoji="🔊")

        return True

    def get_active_mute(
        self,
        user_id: int,
        guild_id: int,
    ) -> Optional[sqlite3.Row]:
        """
        Get active mute for a user in a guild.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Mute record row or None if not muted.
        """
        return self.fetchone(
            """SELECT * FROM active_mutes
               WHERE user_id = ? AND guild_id = ? AND unmuted = 0""",
            (user_id, guild_id)
        )

    def is_user_muted(self: "DatabaseManager", user_id: int, guild_id: int) -> bool:
        """
        Check if a user is muted in a guild.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            True if user has active mute.
        """
        row = self.fetchone(
            "SELECT 1 FROM active_mutes WHERE user_id = ? AND guild_id = ? AND unmuted = 0",
            (user_id, guild_id)
        )
        return row is not None

    def get_expired_mutes(self: "DatabaseManager") -> List[sqlite3.Row]:
        """
        Get all mutes that have expired and need auto-unmute.

        DESIGN:
            Returns mutes where expires_at < current time and not yet unmuted.
            Used by the mute scheduler to process auto-unmutes.

        Returns:
            List of expired mute records.
        """
        now = time.time()
        return self.fetchall(
            """SELECT * FROM active_mutes
               WHERE expires_at IS NOT NULL
               AND expires_at <= ?
               AND unmuted = 0""",
            (now,)
        )

    def get_all_active_mutes(self: "DatabaseManager", guild_id: Optional[int] = None) -> List[sqlite3.Row]:
        """
        Get all active mutes, optionally filtered by guild.

        Args:
            guild_id: Optional guild ID to filter by.

        Returns:
            List of active mute records.
        """
        if guild_id:
            return self.fetchall(
                "SELECT * FROM active_mutes WHERE guild_id = ? AND unmuted = 0",
                (guild_id,)
            )
        return self.fetchall("SELECT * FROM active_mutes WHERE unmuted = 0")

    def get_user_mute_history(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 10,
    ) -> List[sqlite3.Row]:
        """
        Get mute history for a user in a guild.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.

        Returns:
            List of mute history records, newest first.
        """
        return self.fetchall(
            """SELECT * FROM mute_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )

    def get_user_mute_count(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """
        Get total number of mutes for a user in a guild.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Total mute count.
        """
        row = self.fetchone(
            """SELECT COUNT(*) as count FROM mute_history
               WHERE user_id = ? AND guild_id = ? AND action = 'mute'""",
            (user_id, guild_id)
        )
        return row["count"] if row else 0

    def get_mute_moderator_ids(self: "DatabaseManager", user_id: int, guild_id: int) -> List[int]:
        """
        Get all unique moderator IDs who muted/extended a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            List of unique moderator IDs.
        """
        rows = self.fetchall(
            """SELECT DISTINCT moderator_id FROM mute_history
               WHERE user_id = ? AND guild_id = ? AND action = 'mute'
               ORDER BY timestamp DESC""",
            (user_id, guild_id)
        )
        return [row["moderator_id"] for row in rows]
    # =========================================================================
