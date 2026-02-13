"""
AzabBot - Persistent Log Storage
================================

SQLite-based log storage for dashboard with search, filtering, and retention.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================
DB_PATH = Path("data/logs.db")
DEFAULT_RETENTION_DAYS = 7
MAX_QUERY_LIMIT = 500


# =============================================================================
# Log Entry Model
# =============================================================================

@dataclass
class StoredLog:
    """A stored log entry."""
    id: int
    timestamp: datetime
    level: str
    message: str
    module: str
    formatted: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response dict."""
        result = {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() + "Z",
            "level": self.level,
            "message": self.message,
            "module": self.module,
        }
        if self.formatted:
            result["formatted"] = self.formatted
        return result


# =============================================================================
# Log Storage Service
# =============================================================================

class LogStorage:
    """
    SQLite-based persistent log storage.

    Features:
    - Persistent storage across restarts
    - Full-text search on messages
    - Level and date filtering
    - Automatic retention cleanup
    - Thread-safe operations
    """

    def __init__(self, db_path: Path = DB_PATH, retention_days: int = DEFAULT_RETENTION_DAYS):
        self._db_path = db_path
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._registered = False

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

                # Create logs table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        level TEXT NOT NULL,
                        message TEXT NOT NULL,
                        module TEXT NOT NULL,
                        formatted TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes for fast queries
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp DESC)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_logs_module ON logs(module)
                """)

                # Create FTS5 virtual table for full-text search
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS logs_fts USING fts5(
                        message,
                        content='logs',
                        content_rowid='id'
                    )
                """)

                # Create triggers to keep FTS in sync
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS logs_ai AFTER INSERT ON logs BEGIN
                        INSERT INTO logs_fts(rowid, message) VALUES (new.id, new.message);
                    END
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS logs_ad AFTER DELETE ON logs BEGIN
                        INSERT INTO logs_fts(logs_fts, rowid, message) VALUES('delete', old.id, old.message);
                    END
                """)

                conn.commit()
            finally:
                conn.close()

    # =========================================================================
    # Write Operations
    # =========================================================================

    def add(
        self,
        level: str,
        message: str,
        module: str,
        formatted: Optional[str] = None,
    ) -> int:
        """
        Add a log entry to storage.

        Returns:
            The ID of the inserted log entry.
        """
        # Store as UTC so frontend can convert to user's local time
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO logs (timestamp, level, message, module, formatted)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (timestamp, level.upper(), message, module, formatted)
                )
                conn.commit()
                return cursor.lastrowid or 0
            finally:
                conn.close()

    def cleanup_old_logs(self) -> int:
        """
        Delete logs older than retention period.

        Returns:
            Number of deleted logs.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        cutoff_str = cutoff.replace(tzinfo=None).isoformat()

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM logs WHERE timestamp < ?",
                    (cutoff_str,)
                )
                deleted = cursor.rowcount
                conn.commit()

                # Rebuild FTS index
                if deleted > 0:
                    cursor.execute("INSERT INTO logs_fts(logs_fts) VALUES('rebuild')")
                    conn.commit()

                return deleted
            finally:
                conn.close()

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        level: Optional[str] = None,
        module: Optional[str] = None,
        search: Optional[str] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> Tuple[List[StoredLog], int]:
        """
        Query logs with filtering.

        Returns:
            Tuple of (logs, total_count)
        """
        limit = min(limit, MAX_QUERY_LIMIT)

        conditions = []
        params: List[Any] = []

        # Level filter
        if level and level.upper() != "ALL":
            conditions.append("level = ?")
            params.append(level.upper())

        # Module filter
        if module:
            conditions.append("module = ?")
            params.append(module)

        # Time range filter
        if from_time:
            from_str = from_time.replace(tzinfo=None).isoformat()
            conditions.append("timestamp >= ?")
            params.append(from_str)

        if to_time:
            to_str = to_time.replace(tzinfo=None).isoformat()
            conditions.append("timestamp <= ?")
            params.append(to_str)

        # Full-text search
        if search:
            conditions.append("id IN (SELECT rowid FROM logs_fts WHERE logs_fts MATCH ?)")
            # Escape special FTS5 characters and add prefix matching
            search_term = search.replace('"', '""')
            params.append(f'"{search_term}"*')

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                # Get total count
                cursor.execute(f"SELECT COUNT(*) FROM logs WHERE {where_clause}", params)
                total = cursor.fetchone()[0]

                # Get logs
                cursor.execute(
                    f"""
                    SELECT id, timestamp, level, message, module, formatted
                    FROM logs
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset]
                )

                logs = []
                for row in cursor.fetchall():
                    logs.append(StoredLog(
                        id=row["id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        level=row["level"],
                        message=row["message"],
                        module=row["module"],
                        formatted=row["formatted"],
                    ))

                return logs, total
            finally:
                conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get log statistics."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                # Total count
                cursor.execute("SELECT COUNT(*) FROM logs")
                total = cursor.fetchone()[0]

                # Count by level
                cursor.execute("""
                    SELECT level, COUNT(*) as count
                    FROM logs
                    GROUP BY level
                """)
                by_level = {row["level"]: row["count"] for row in cursor.fetchall()}

                # Count by module (top 10)
                cursor.execute("""
                    SELECT module, COUNT(*) as count
                    FROM logs
                    GROUP BY module
                    ORDER BY count DESC
                    LIMIT 10
                """)
                by_module = {row["module"]: row["count"] for row in cursor.fetchall()}

                # Recent activity (last 24h by hour)
                yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None).isoformat()
                cursor.execute("""
                    SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
                    FROM logs
                    WHERE timestamp >= ?
                    GROUP BY hour
                    ORDER BY hour
                """, (yesterday,))
                by_hour = {row["hour"]: row["count"] for row in cursor.fetchall()}

                return {
                    "total": total,
                    "by_level": by_level,
                    "by_module": by_module,
                    "by_hour": by_hour,
                    "retention_days": self._retention_days,
                }
            finally:
                conn.close()

    def get_modules(self) -> List[str]:
        """Get list of unique modules."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT module FROM logs ORDER BY module")
                return [row["module"] for row in cursor.fetchall()]
            finally:
                conn.close()

    # =========================================================================
    # Logger Integration
    # =========================================================================

    def register_with_logger(self) -> None:
        """Register this storage to receive logs from the logger."""
        if self._registered:
            return

        logger.on_log(self._on_log)
        self._registered = True

        logger.tree("Log Storage Initialized", [
            ("Database", str(self._db_path)),
            ("Retention", f"{self._retention_days} days"),
        ], emoji="💾")

    def _on_log(
        self,
        level: str,
        message: str,
        module: str,
        formatted: Optional[str] = None,
    ) -> None:
        """Callback from logger."""
        try:
            self.add(level, message, module, formatted)
        except (KeyError, TypeError, RuntimeError):
            pass  # Don't let storage errors break logging


# =============================================================================
# Singleton
# =============================================================================

_storage: Optional[LogStorage] = None


def get_log_storage() -> LogStorage:
    """Get the log storage singleton."""
    global _storage
    if _storage is None:
        _storage = LogStorage()
        _storage.register_with_logger()
    return _storage


__all__ = ["LogStorage", "StoredLog", "get_log_storage"]
