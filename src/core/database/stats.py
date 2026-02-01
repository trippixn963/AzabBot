"""
AzabBot - Database Statistics Module
====================================

Statistics and metrics database operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import NY_TZ

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class StatsMixin:
    """Mixin for statistics database operations."""

    # Stats API Helper Methods
    # =========================================================================

    def get_mutes_in_range(self: "DatabaseManager", start_ts: float, end_ts: float, guild_id: Optional[int] = None) -> int:
        """Get count of mutes in a time range."""
        if guild_id:
            row = self.fetchone(
                """SELECT COUNT(*) as count FROM mute_history
                   WHERE action = 'mute' AND timestamp >= ? AND timestamp <= ? AND guild_id = ?""",
                (start_ts, end_ts, guild_id)
            )
        else:
            row = self.fetchone(
                """SELECT COUNT(*) as count FROM mute_history
                   WHERE action = 'mute' AND timestamp >= ? AND timestamp <= ?""",
                (start_ts, end_ts)
            )
        return row["count"] if row else 0

    def get_bans_in_range(self: "DatabaseManager", start_ts: float, end_ts: float, guild_id: Optional[int] = None) -> int:
        """Get count of bans in a time range."""
        if guild_id:
            row = self.fetchone(
                """SELECT COUNT(*) as count FROM ban_history
                   WHERE action = 'ban' AND timestamp >= ? AND timestamp <= ? AND guild_id = ?""",
                (start_ts, end_ts, guild_id)
            )
        else:
            row = self.fetchone(
                """SELECT COUNT(*) as count FROM ban_history
                   WHERE action = 'ban' AND timestamp >= ? AND timestamp <= ?""",
                (start_ts, end_ts)
            )
        return row["count"] if row else 0

    def get_warns_in_range(self: "DatabaseManager", start_ts: float, end_ts: float, guild_id: Optional[int] = None) -> int:
        """Get count of warnings in a time range."""
        if guild_id:
            row = self.fetchone(
                """SELECT COUNT(*) as count FROM warnings
                   WHERE created_at >= ? AND created_at <= ? AND guild_id = ?""",
                (start_ts, end_ts, guild_id)
            )
        else:
            row = self.fetchone(
                """SELECT COUNT(*) as count FROM warnings
                   WHERE created_at >= ? AND created_at <= ?""",
                (start_ts, end_ts)
            )
        return row["count"] if row else 0

    def get_total_mutes(self: "DatabaseManager", guild_id: Optional[int] = None) -> int:
        """Get total mute count."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM mute_history WHERE action = 'mute' AND guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM mute_history WHERE action = 'mute'")
        return row["count"] if row else 0

    def get_total_bans(self: "DatabaseManager", guild_id: Optional[int] = None) -> int:
        """Get total ban count."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM ban_history WHERE action = 'ban' AND guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM ban_history WHERE action = 'ban'")
        return row["count"] if row else 0

    def get_total_warns(self: "DatabaseManager", guild_id: Optional[int] = None) -> int:
        """Get total warning count."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM warnings WHERE guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM warnings")
        return row["count"] if row else 0

    def get_total_cases(self: "DatabaseManager", guild_id: Optional[int] = None) -> int:
        """Get total case count."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM cases WHERE guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM cases")
        return row["count"] if row else 0

    def get_active_prisoners_count(self: "DatabaseManager", guild_id: Optional[int] = None) -> int:
        """Get count of currently active mutes."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM active_mutes WHERE unmuted = 0 AND guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM active_mutes WHERE unmuted = 0")
        return row["count"] if row else 0

    def get_open_cases_count(self: "DatabaseManager", guild_id: Optional[int] = None) -> int:
        """Get count of open cases."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM cases WHERE status = 'open' AND guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM cases WHERE status = 'open'")
        return row["count"] if row else 0

    def get_top_offenders(self: "DatabaseManager", limit: int = 10, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get top offenders by total infractions (mutes + bans + warns)."""
        if guild_id:
            rows = self.fetchall(
                """
                SELECT
                    user_id,
                    SUM(mute_count) as mutes,
                    SUM(ban_count) as bans,
                    SUM(warn_count) as warns,
                    (SUM(mute_count) + SUM(ban_count) + SUM(warn_count)) as total
                FROM (
                    SELECT user_id, COUNT(*) as mute_count, 0 as ban_count, 0 as warn_count
                    FROM mute_history WHERE action = 'mute' AND guild_id = ?
                    GROUP BY user_id
                    UNION ALL
                    SELECT user_id, 0 as mute_count, COUNT(*) as ban_count, 0 as warn_count
                    FROM ban_history WHERE action = 'ban' AND guild_id = ?
                    GROUP BY user_id
                    UNION ALL
                    SELECT user_id, 0 as mute_count, 0 as ban_count, COUNT(*) as warn_count
                    FROM warnings WHERE guild_id = ?
                    GROUP BY user_id
                ) combined
                GROUP BY user_id
                ORDER BY total DESC
                LIMIT ?
                """,
                (guild_id, guild_id, guild_id, limit)
            )
        else:
            rows = self.fetchall(
                """
                SELECT
                    user_id,
                    SUM(mute_count) as mutes,
                    SUM(ban_count) as bans,
                    SUM(warn_count) as warns,
                    (SUM(mute_count) + SUM(ban_count) + SUM(warn_count)) as total
                FROM (
                    SELECT user_id, COUNT(*) as mute_count, 0 as ban_count, 0 as warn_count
                    FROM mute_history WHERE action = 'mute'
                    GROUP BY user_id
                    UNION ALL
                    SELECT user_id, 0 as mute_count, COUNT(*) as ban_count, 0 as warn_count
                    FROM ban_history WHERE action = 'ban'
                    GROUP BY user_id
                    UNION ALL
                    SELECT user_id, 0 as mute_count, 0 as ban_count, COUNT(*) as warn_count
                    FROM warnings
                    GROUP BY user_id
                ) combined
                GROUP BY user_id
                ORDER BY total DESC
                LIMIT ?
                """,
                (limit,)
            )
        return [dict(row) for row in rows] if rows else []

    def get_recent_actions(self: "DatabaseManager", limit: int = 10, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get most recent moderation actions."""
        if guild_id:
            rows = self.fetchall(
                """
                SELECT * FROM (
                    SELECT 'mute' as type, user_id, moderator_id, reason, timestamp, guild_id
                    FROM mute_history WHERE action = 'mute' AND guild_id = ?
                    UNION ALL
                    SELECT 'ban' as type, user_id, moderator_id, reason, timestamp, guild_id
                    FROM ban_history WHERE action = 'ban' AND guild_id = ?
                    UNION ALL
                    SELECT 'warn' as type, user_id, moderator_id, reason, created_at as timestamp, guild_id
                    FROM warnings WHERE guild_id = ?
                ) combined
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (guild_id, guild_id, guild_id, limit)
            )
        else:
            rows = self.fetchall(
                """
                SELECT * FROM (
                    SELECT 'mute' as type, user_id, moderator_id, reason, timestamp, guild_id
                    FROM mute_history WHERE action = 'mute'
                    UNION ALL
                    SELECT 'ban' as type, user_id, moderator_id, reason, timestamp, guild_id
                    FROM ban_history WHERE action = 'ban'
                    UNION ALL
                    SELECT 'warn' as type, user_id, moderator_id, reason, created_at as timestamp, guild_id
                    FROM warnings
                ) combined
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,)
            )
        return [dict(row) for row in rows] if rows else []

    def get_moderator_stats(self: "DatabaseManager", moderator_id: int, guild_id: Optional[int] = None) -> Dict[str, Any]:
        """Get stats for a specific moderator."""
        if guild_id:
            row = self.fetchone(
                """
                SELECT
                    (SELECT COUNT(*) FROM mute_history WHERE moderator_id = ? AND guild_id = ?) as mutes_issued,
                    (SELECT COUNT(*) FROM ban_history WHERE moderator_id = ? AND guild_id = ?) as bans_issued,
                    (SELECT COUNT(*) FROM warnings WHERE moderator_id = ? AND guild_id = ?) as warns_issued
                """,
                (moderator_id, guild_id, moderator_id, guild_id, moderator_id, guild_id)
            )
        else:
            row = self.fetchone(
                """
                SELECT
                    (SELECT COUNT(*) FROM mute_history WHERE moderator_id = ?) as mutes_issued,
                    (SELECT COUNT(*) FROM ban_history WHERE moderator_id = ?) as bans_issued,
                    (SELECT COUNT(*) FROM warnings WHERE moderator_id = ?) as warns_issued
                """,
                (moderator_id, moderator_id, moderator_id)
            )

        if row:
            result = dict(row)
            result["total_actions"] = (
                result.get("mutes_issued", 0) +
                result.get("bans_issued", 0) +
                result.get("warns_issued", 0)
            )
            return result
        return {"mutes_issued": 0, "bans_issued": 0, "warns_issued": 0, "total_actions": 0}

    def get_moderator_actions(
        self,
        moderator_id: int,
        limit: int = 10,
        guild_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get recent actions by a specific moderator."""
        if guild_id:
            rows = self.fetchall(
                """
                SELECT type, user_id, reason, timestamp FROM (
                    SELECT 'mute' as type, user_id, reason, timestamp
                    FROM mute_history
                    WHERE moderator_id = ? AND guild_id = ?

                    UNION ALL

                    SELECT 'ban' as type, user_id, reason, timestamp
                    FROM ban_history
                    WHERE moderator_id = ? AND guild_id = ?

                    UNION ALL

                    SELECT 'warn' as type, user_id, reason, created_at as timestamp
                    FROM warnings
                    WHERE moderator_id = ? AND guild_id = ?
                ) combined
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (moderator_id, guild_id, moderator_id, guild_id, moderator_id, guild_id, limit)
            )
        else:
            rows = self.fetchall(
                """
                SELECT type, user_id, reason, timestamp FROM (
                    SELECT 'mute' as type, user_id, reason, timestamp
                    FROM mute_history
                    WHERE moderator_id = ?

                    UNION ALL

                    SELECT 'ban' as type, user_id, reason, timestamp
                    FROM ban_history
                    WHERE moderator_id = ?

                    UNION ALL

                    SELECT 'warn' as type, user_id, reason, created_at as timestamp
                    FROM warnings
                    WHERE moderator_id = ?
                ) combined
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (moderator_id, moderator_id, moderator_id, limit)
            )
        return [dict(row) for row in rows] if rows else []

    def get_user_punishments(
        self,
        user_id: int,
        limit: int = 10,
        guild_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get recent punishments received by a user."""
        if guild_id:
            rows = self.fetchall(
                """
                SELECT type, moderator_id, reason, timestamp FROM (
                    SELECT 'mute' as type, moderator_id, reason, timestamp
                    FROM mute_history
                    WHERE user_id = ? AND guild_id = ?

                    UNION ALL

                    SELECT 'ban' as type, moderator_id, reason, timestamp
                    FROM ban_history
                    WHERE user_id = ? AND guild_id = ?

                    UNION ALL

                    SELECT 'warn' as type, moderator_id, reason, created_at as timestamp
                    FROM warnings
                    WHERE user_id = ? AND guild_id = ?
                ) combined
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, guild_id, user_id, guild_id, user_id, guild_id, limit)
            )
        else:
            rows = self.fetchall(
                """
                SELECT type, moderator_id, reason, timestamp FROM (
                    SELECT 'mute' as type, moderator_id, reason, timestamp
                    FROM mute_history
                    WHERE user_id = ?

                    UNION ALL

                    SELECT 'ban' as type, moderator_id, reason, timestamp
                    FROM ban_history
                    WHERE user_id = ?

                    UNION ALL

                    SELECT 'warn' as type, moderator_id, reason, created_at as timestamp
                    FROM warnings
                    WHERE user_id = ?
                ) combined
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, user_id, user_id, limit)
            )
        return [dict(row) for row in rows] if rows else []

    def get_moderator_leaderboard(self: "DatabaseManager", limit: int = 10, exclude_user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get moderator leaderboard by action count with mutes/bans/warns breakdown."""
        if exclude_user_id:
            rows = self.fetchall(
                """
                SELECT
                    moderator_id,
                    SUM(mutes) as mutes,
                    SUM(bans) as bans,
                    SUM(warns) as warns,
                    SUM(mutes + bans + warns) as total_actions
                FROM (
                    SELECT moderator_id, 1 as mutes, 0 as bans, 0 as warns FROM mute_history
                    UNION ALL
                    SELECT moderator_id, 0 as mutes, 1 as bans, 0 as warns FROM ban_history WHERE action = 'ban'
                    UNION ALL
                    SELECT moderator_id, 0 as mutes, 0 as bans, 1 as warns FROM warnings
                )
                WHERE moderator_id != ?
                GROUP BY moderator_id
                ORDER BY total_actions DESC
                LIMIT ?
                """,
                (exclude_user_id, limit)
            )
        else:
            rows = self.fetchall(
                """
                SELECT
                    moderator_id,
                    SUM(mutes) as mutes,
                    SUM(bans) as bans,
                    SUM(warns) as warns,
                    SUM(mutes + bans + warns) as total_actions
                FROM (
                    SELECT moderator_id, 1 as mutes, 0 as bans, 0 as warns FROM mute_history
                    UNION ALL
                    SELECT moderator_id, 0 as mutes, 1 as bans, 0 as warns FROM ban_history WHERE action = 'ban'
                    UNION ALL
                    SELECT moderator_id, 0 as mutes, 0 as bans, 1 as warns FROM warnings
                )
                GROUP BY moderator_id
                ORDER BY total_actions DESC
                LIMIT ?
                """,
                (limit,)
            )
        return [dict(row) for row in rows] if rows else []

    def get_repeat_offenders(self: "DatabaseManager", min_offenses: int = 3, limit: int = 5, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get users with 3+ total punishments (repeat offenders)."""
        if guild_id:
            rows = self.fetchall(
                """
                SELECT
                    user_id,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns,
                    COUNT(*) as total
                FROM (
                    SELECT user_id, 'mute' as action_type FROM mute_history WHERE guild_id = ?
                    UNION ALL
                    SELECT user_id, 'ban' as action_type FROM ban_history WHERE guild_id = ?
                    UNION ALL
                    SELECT user_id, 'warn' as action_type FROM warnings WHERE guild_id = ?
                )
                GROUP BY user_id
                HAVING total >= ?
                ORDER BY total DESC
                LIMIT ?
                """,
                (guild_id, guild_id, guild_id, min_offenses, limit)
            )
        else:
            rows = self.fetchall(
                """
                SELECT
                    user_id,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns,
                    COUNT(*) as total
                FROM (
                    SELECT user_id, 'mute' as action_type FROM mute_history
                    UNION ALL
                    SELECT user_id, 'ban' as action_type FROM ban_history
                    UNION ALL
                    SELECT user_id, 'warn' as action_type FROM warnings
                )
                GROUP BY user_id
                HAVING total >= ?
                ORDER BY total DESC
                LIMIT ?
                """,
                (min_offenses, limit)
            )
        return [dict(row) for row in rows] if rows else []

    def get_recent_releases(self: "DatabaseManager", limit: int = 5, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get recently released prisoners (unmuted users)."""
        # Note: active_mutes doesn't have unmuted_at, so we use expires_at as proxy
        # For manual unmutes, expires_at would be the scheduled time
        if guild_id:
            rows = self.fetchall(
                """
                SELECT
                    user_id,
                    muted_at,
                    expires_at,
                    CAST((COALESCE(expires_at, strftime('%s', 'now')) - muted_at) / 60 AS INTEGER) as duration_minutes
                FROM active_mutes
                WHERE guild_id = ? AND unmuted = 1
                ORDER BY expires_at DESC
                LIMIT ?
                """,
                (guild_id, limit)
            )
        else:
            rows = self.fetchall(
                """
                SELECT
                    user_id,
                    muted_at,
                    expires_at,
                    CAST((COALESCE(expires_at, strftime('%s', 'now')) - muted_at) / 60 AS INTEGER) as duration_minutes
                FROM active_mutes
                WHERE unmuted = 1
                ORDER BY expires_at DESC
                LIMIT ?
                """,
                (limit,)
            )
        return [dict(row) for row in rows] if rows else []

    def get_all_time_top_moderator(self: "DatabaseManager", guild_id: Optional[int] = None, exclude_user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get the top moderator of all time based on total actions.

        Args:
            guild_id: Optional guild ID to filter by
            exclude_user_id: Optional user ID to exclude (e.g., the bot itself)
        """
        # Build query based on parameters to avoid f-string SQL injection
        if guild_id and exclude_user_id:
            row = self.fetchone(
                """
                SELECT
                    moderator_id,
                    COUNT(*) as total_actions,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
                FROM (
                    SELECT moderator_id, 'mute' as action_type FROM mute_history WHERE guild_id = ?
                    UNION ALL
                    SELECT moderator_id, 'ban' as action_type FROM ban_history WHERE guild_id = ?
                    UNION ALL
                    SELECT moderator_id, 'warn' as action_type FROM warnings WHERE guild_id = ?
                )
                WHERE moderator_id != ?
                GROUP BY moderator_id
                ORDER BY total_actions DESC
                LIMIT 1
                """,
                (guild_id, guild_id, guild_id, exclude_user_id)
            )
        elif guild_id:
            row = self.fetchone(
                """
                SELECT
                    moderator_id,
                    COUNT(*) as total_actions,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
                FROM (
                    SELECT moderator_id, 'mute' as action_type FROM mute_history WHERE guild_id = ?
                    UNION ALL
                    SELECT moderator_id, 'ban' as action_type FROM ban_history WHERE guild_id = ?
                    UNION ALL
                    SELECT moderator_id, 'warn' as action_type FROM warnings WHERE guild_id = ?
                )
                GROUP BY moderator_id
                ORDER BY total_actions DESC
                LIMIT 1
                """,
                (guild_id, guild_id, guild_id)
            )
        elif exclude_user_id:
            row = self.fetchone(
                """
                SELECT
                    moderator_id,
                    COUNT(*) as total_actions,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
                FROM (
                    SELECT moderator_id, 'mute' as action_type FROM mute_history
                    UNION ALL
                    SELECT moderator_id, 'ban' as action_type FROM ban_history
                    UNION ALL
                    SELECT moderator_id, 'warn' as action_type FROM warnings
                )
                WHERE moderator_id != ?
                GROUP BY moderator_id
                ORDER BY total_actions DESC
                LIMIT 1
                """,
                (exclude_user_id,)
            )
        else:
            row = self.fetchone(
                """
                SELECT
                    moderator_id,
                    COUNT(*) as total_actions,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
                FROM (
                    SELECT moderator_id, 'mute' as action_type FROM mute_history
                    UNION ALL
                    SELECT moderator_id, 'ban' as action_type FROM ban_history
                    UNION ALL
                    SELECT moderator_id, 'warn' as action_type FROM warnings
                )
                GROUP BY moderator_id
                ORDER BY total_actions DESC
                LIMIT 1
                """
            )

        return dict(row) if row else None

    def get_weekly_top_moderator(self: "DatabaseManager", guild_id: Optional[int] = None, exclude_user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get the top moderator for this week based on actions.

        Args:
            guild_id: Optional guild ID to filter by
            exclude_user_id: Optional user ID to exclude (e.g., the bot itself)
        """
        week_start = time.time() - (7 * 24 * 60 * 60)

        # Build query based on parameters to avoid f-string SQL injection
        if guild_id and exclude_user_id:
            row = self.fetchone(
                """
                SELECT
                    moderator_id,
                    COUNT(*) as weekly_actions,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
                FROM (
                    SELECT moderator_id, 'mute' as action_type FROM mute_history WHERE timestamp >= ? AND guild_id = ?
                    UNION ALL
                    SELECT moderator_id, 'ban' as action_type FROM ban_history WHERE timestamp >= ? AND guild_id = ?
                    UNION ALL
                    SELECT moderator_id, 'warn' as action_type FROM warnings WHERE created_at >= ? AND guild_id = ?
                )
                WHERE moderator_id != ?
                GROUP BY moderator_id
                ORDER BY weekly_actions DESC
                LIMIT 1
                """,
                (week_start, guild_id, week_start, guild_id, week_start, guild_id, exclude_user_id)
            )
        elif guild_id:
            row = self.fetchone(
                """
                SELECT
                    moderator_id,
                    COUNT(*) as weekly_actions,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
                FROM (
                    SELECT moderator_id, 'mute' as action_type FROM mute_history WHERE timestamp >= ? AND guild_id = ?
                    UNION ALL
                    SELECT moderator_id, 'ban' as action_type FROM ban_history WHERE timestamp >= ? AND guild_id = ?
                    UNION ALL
                    SELECT moderator_id, 'warn' as action_type FROM warnings WHERE created_at >= ? AND guild_id = ?
                )
                GROUP BY moderator_id
                ORDER BY weekly_actions DESC
                LIMIT 1
                """,
                (week_start, guild_id, week_start, guild_id, week_start, guild_id)
            )
        elif exclude_user_id:
            row = self.fetchone(
                """
                SELECT
                    moderator_id,
                    COUNT(*) as weekly_actions,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
                FROM (
                    SELECT moderator_id, 'mute' as action_type FROM mute_history WHERE timestamp >= ?
                    UNION ALL
                    SELECT moderator_id, 'ban' as action_type FROM ban_history WHERE timestamp >= ?
                    UNION ALL
                    SELECT moderator_id, 'warn' as action_type FROM warnings WHERE created_at >= ?
                )
                WHERE moderator_id != ?
                GROUP BY moderator_id
                ORDER BY weekly_actions DESC
                LIMIT 1
                """,
                (week_start, week_start, week_start, exclude_user_id)
            )
        else:
            row = self.fetchone(
                """
                SELECT
                    moderator_id,
                    COUNT(*) as weekly_actions,
                    SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                    SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                    SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
                FROM (
                    SELECT moderator_id, 'mute' as action_type FROM mute_history WHERE timestamp >= ?
                    UNION ALL
                    SELECT moderator_id, 'ban' as action_type FROM ban_history WHERE timestamp >= ?
                    UNION ALL
                    SELECT moderator_id, 'warn' as action_type FROM warnings WHERE created_at >= ?
                )
                GROUP BY moderator_id
                ORDER BY weekly_actions DESC
                LIMIT 1
                """,
                (week_start, week_start, week_start)
            )
        return dict(row) if row else None


# =============================================================================
