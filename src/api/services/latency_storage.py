"""
AzabBot - Latency Storage Service
=================================

SQLite-based persistent latency tracking for dashboard graphs.
Stores both Discord and API latency with time-based aggregation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
from dataclasses import dataclass

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

DB_PATH = Path("data/latency.db")
DEFAULT_RETENTION_DAYS = 30
MAX_LIVE_POINTS = 60


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class LatencyPoint:
    """A single latency measurement."""
    timestamp: datetime
    discord_ms: int
    api_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response dict."""
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "discord_ms": self.discord_ms,
            "api_ms": self.api_ms,
        }


@dataclass
class AggregatedLatency:
    """Aggregated latency for a time period."""
    timestamp: datetime
    discord_avg: float
    discord_min: int
    discord_max: int
    api_avg: Optional[float] = None
    api_min: Optional[int] = None
    api_max: Optional[int] = None
    count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response dict."""
        result = {
            "timestamp": self.timestamp.isoformat() + "Z",
            "discord_avg": round(self.discord_avg, 1),
            "discord_min": self.discord_min,
            "discord_max": self.discord_max,
            "count": self.count,
        }
        if self.api_avg is not None:
            result["api_avg"] = round(self.api_avg, 1)
            result["api_min"] = self.api_min
            result["api_max"] = self.api_max
        return result


# =============================================================================
# Latency Storage Service
# =============================================================================

class LatencyStorage:
    """
    SQLite-based persistent latency storage.

    Features:
    - Stores Discord and API latency readings
    - Time-based queries with aggregation (hourly, daily)
    - Automatic retention cleanup (30 days)
    - Thread-safe operations
    """

    def __init__(self, db_path: Path = DB_PATH, retention_days: int = DEFAULT_RETENTION_DAYS):
        self._db_path = db_path
        self._retention_days = retention_days
        self._lock = threading.Lock()

        # Ensure data directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                # Create latency table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS latency (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        discord_ms INTEGER NOT NULL,
                        api_ms INTEGER,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes for fast time-based queries
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_latency_timestamp
                    ON latency(timestamp DESC)
                """)

                conn.commit()
            finally:
                conn.close()

    # =========================================================================
    # Write Operations
    # =========================================================================

    def record(self, discord_ms: int, api_ms: Optional[int] = None) -> int:
        """
        Record a latency measurement.

        Args:
            discord_ms: Discord WebSocket latency in milliseconds
            api_ms: Optional API response latency in milliseconds

        Returns:
            The ID of the inserted record.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO latency (timestamp, discord_ms, api_ms)
                    VALUES (?, ?, ?)
                    """,
                    (timestamp, discord_ms, api_ms)
                )
                conn.commit()
                return cursor.lastrowid or 0
            finally:
                conn.close()

    def update_latest_api_latency(self, api_ms: int) -> bool:
        """
        Update the most recent record with API latency.

        This is called by the frontend to report API response time.
        We update the most recent record (within last 5 seconds) to
        associate API latency with the corresponding Discord latency.

        Args:
            api_ms: API response latency in milliseconds

        Returns:
            True if a record was updated, False otherwise.
        """
        # Only update records from the last 5 seconds
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=5)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                # Update the most recent record that doesn't have API latency yet
                cursor.execute(
                    """
                    UPDATE latency
                    SET api_ms = ?
                    WHERE id = (
                        SELECT id FROM latency
                        WHERE timestamp >= ? AND api_ms IS NULL
                        ORDER BY timestamp DESC
                        LIMIT 1
                    )
                    """,
                    (api_ms, cutoff_str)
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def cleanup_old_data(self) -> int:
        """
        Delete latency data older than retention period.

        Returns:
            Number of deleted records.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM latency WHERE timestamp < ?",
                    (cutoff_str,)
                )
                deleted = cursor.rowcount
                conn.commit()

                if deleted > 0:
                    # Vacuum to reclaim space
                    cursor.execute("VACUUM")

                return deleted
            finally:
                conn.close()

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get_live(self, limit: int = MAX_LIVE_POINTS) -> List[LatencyPoint]:
        """
        Get most recent latency points for live view.

        Args:
            limit: Maximum number of points to return

        Returns:
            List of LatencyPoint (oldest first for graphing)
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT timestamp, discord_ms, api_ms
                    FROM latency
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,)
                )

                points = []
                for row in cursor.fetchall():
                    points.append(LatencyPoint(
                        timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                        discord_ms=row["discord_ms"],
                        api_ms=row["api_ms"],
                    ))

                # Reverse to get oldest first (for graphing left-to-right)
                return list(reversed(points))
            finally:
                conn.close()

    def get_hourly(self, hours: int = 24) -> List[AggregatedLatency]:
        """
        Get hourly aggregated latency for the last N hours.

        Args:
            hours: Number of hours to look back

        Returns:
            List of AggregatedLatency per hour
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT
                        strftime('%Y-%m-%dT%H:00:00Z', timestamp) as hour,
                        AVG(discord_ms) as discord_avg,
                        MIN(discord_ms) as discord_min,
                        MAX(discord_ms) as discord_max,
                        AVG(api_ms) as api_avg,
                        MIN(api_ms) as api_min,
                        MAX(api_ms) as api_max,
                        COUNT(*) as count
                    FROM latency
                    WHERE timestamp >= ?
                    GROUP BY hour
                    ORDER BY hour ASC
                    """,
                    (cutoff_str,)
                )

                results = []
                for row in cursor.fetchall():
                    results.append(AggregatedLatency(
                        timestamp=datetime.fromisoformat(row["hour"].replace("Z", "+00:00")),
                        discord_avg=row["discord_avg"] or 0,
                        discord_min=row["discord_min"] or 0,
                        discord_max=row["discord_max"] or 0,
                        api_avg=row["api_avg"],
                        api_min=row["api_min"],
                        api_max=row["api_max"],
                        count=row["count"],
                    ))

                return results
            finally:
                conn.close()

    def get_daily(self, days: int = 30) -> List[AggregatedLatency]:
        """
        Get daily aggregated latency for the last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of AggregatedLatency per day
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT
                        strftime('%Y-%m-%dT00:00:00Z', timestamp) as day,
                        AVG(discord_ms) as discord_avg,
                        MIN(discord_ms) as discord_min,
                        MAX(discord_ms) as discord_max,
                        AVG(api_ms) as api_avg,
                        MIN(api_ms) as api_min,
                        MAX(api_ms) as api_max,
                        COUNT(*) as count
                    FROM latency
                    WHERE timestamp >= ?
                    GROUP BY day
                    ORDER BY day ASC
                    """,
                    (cutoff_str,)
                )

                results = []
                for row in cursor.fetchall():
                    results.append(AggregatedLatency(
                        timestamp=datetime.fromisoformat(row["day"].replace("Z", "+00:00")),
                        discord_avg=row["discord_avg"] or 0,
                        discord_min=row["discord_min"] or 0,
                        discord_max=row["discord_max"] or 0,
                        api_avg=row["api_avg"],
                        api_min=row["api_min"],
                        api_max=row["api_max"],
                        count=row["count"],
                    ))

                return results
            finally:
                conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get latency statistics."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                # Get overall stats
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        AVG(discord_ms) as discord_avg,
                        MIN(discord_ms) as discord_min,
                        MAX(discord_ms) as discord_max,
                        AVG(api_ms) as api_avg,
                        MIN(api_ms) as api_min,
                        MAX(api_ms) as api_max
                    FROM latency
                """)
                row = cursor.fetchone()

                # Get last 24h stats
                yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        AVG(discord_ms) as discord_avg
                    FROM latency
                    WHERE timestamp >= ?
                """, (yesterday,))
                last_24h = cursor.fetchone()

                return {
                    "total_records": row["total"],
                    "discord": {
                        "avg": round(row["discord_avg"] or 0, 1),
                        "min": row["discord_min"] or 0,
                        "max": row["discord_max"] or 0,
                    },
                    "api": {
                        "avg": round(row["api_avg"] or 0, 1) if row["api_avg"] else None,
                        "min": row["api_min"],
                        "max": row["api_max"],
                    },
                    "last_24h": {
                        "count": last_24h["total"],
                        "discord_avg": round(last_24h["discord_avg"] or 0, 1),
                    },
                    "retention_days": self._retention_days,
                }
            finally:
                conn.close()


# =============================================================================
# Singleton
# =============================================================================

_storage: Optional[LatencyStorage] = None


def get_latency_storage() -> LatencyStorage:
    """Get the latency storage singleton."""
    global _storage
    if _storage is None:
        _storage = LatencyStorage()
    return _storage


__all__ = ["LatencyStorage", "LatencyPoint", "AggregatedLatency", "get_latency_storage"]
