"""
AzabBot - Database Manager
==========================

Central SQLite database manager for all bot data.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
import threading
import asyncio
import time
from pathlib import Path
from typing import Optional, List, Tuple, Any, Dict

from src.core.logger import logger
from src.core.config import NY_TZ
from src.core.constants import DB_CONNECTION_TIMEOUT, SQLITE_BUSY_TIMEOUT

# Import all mixins
from src.core.database.schema import SchemaMixin
from src.core.database.tickets import TicketsMixin
from src.core.database.cases import CasesMixin
from src.core.database.legacy_cases import LegacyCasesMixin
from src.core.database.warnings import WarningsMixin
from src.core.database.mutes import MutesMixin
from src.core.database.stats import StatsMixin
from src.core.database.detection import DetectionMixin
from src.core.database.lockdown import LockdownMixin
from src.core.database.state import StateMixin
from src.core.database.mod_tracker import ModTrackerMixin
from src.core.database.history import HistoryMixin
from src.core.database.activity import ActivityMixin
from src.core.database.pending import PendingMixin
from src.core.database.voice import VoiceMixin
from src.core.database.snipe import SnipeMixin
from src.core.database.appeals import AppealsMixin
from src.core.database.linked import LinkedMixin
from src.core.database.timeouts import TimeoutsMixin
from src.core.database.snapshots import SnapshotsMixin
from src.core.database.token_blacklist import TokenBlacklistMixin

# Import type definitions from models module
from src.core.database.models import (
    MuteRecord,
    CaseLogRecord,
    TrackedModRecord,
    JoinInfoRecord,
    ModNoteRecord,
    UsernameHistoryRecord,
    AppealRecord,
    MemberActivityRecord,
    PendingReasonRecord,
    TicketRecord,
)


# =============================================================================
# Type Definitions (imported from types.py)
# =============================================================================

# Re-export for backward compatibility
__all_types__ = [
    "MuteRecord",
    "CaseLogRecord",
    "TrackedModRecord",
    "JoinInfoRecord",
    "ModNoteRecord",
    "UsernameHistoryRecord",
    "AppealRecord",
    "MemberActivityRecord",
    "PendingReasonRecord",
    "TicketRecord",
]


# =============================================================================
# Constants
# =============================================================================

# Path: src/core/database/manager.py -> go up 4 levels to reach project root
DATA_DIR: Path = Path(__file__).parent.parent.parent.parent / "data"
DB_PATH: Path = DATA_DIR / "azab.db"


# =============================================================================
# Database Manager (Singleton)
# =============================================================================

class DatabaseManager(
    SchemaMixin,
    TicketsMixin,
    CasesMixin,
    LegacyCasesMixin,
    WarningsMixin,
    MutesMixin,
    StatsMixin,
    DetectionMixin,
    LockdownMixin,
    StateMixin,
    ModTrackerMixin,
    HistoryMixin,
    ActivityMixin,
    PendingMixin,
    VoiceMixin,
    SnipeMixin,
    AppealsMixin,
    LinkedMixin,
    TimeoutsMixin,
    SnapshotsMixin,
    TokenBlacklistMixin,
):
    """
    Centralized database manager with thread-safe operations.

    DESIGN: Singleton pattern ensures single database connection.
    Uses WAL mode for better concurrency with multiple readers.
    All operations are thread-safe via internal locking.
    """

    _instance: Optional["DatabaseManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "DatabaseManager":
        """Singleton pattern - only one instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize database connection and tables."""
        if self._initialized:
            return

        self._db_lock: threading.Lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

        # Cache for expensive queries (TTL-based)
        self._prisoner_stats_cache: Dict[int, tuple] = {}  # user_id -> (stats, timestamp)
        self._prisoner_stats_ttl: int = 60  # 60 seconds
        self._prisoner_stats_lock = asyncio.Lock()  # Protect concurrent cache access

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._connect()
        self._init_tables()
        self._initialized = True

        logger.tree("Database Manager Initialized", [
            ("Path", str(DB_PATH)),
            ("WAL Mode", "Enabled"),
            ("Cache Size", "64MB"),
        ], emoji="🗄️")

    # =========================================================================
    # Connection Management
    # =========================================================================

    def _connect(self) -> None:
        """
        Establish database connection with WAL mode.

        DESIGN: WAL mode provides better concurrency for read-heavy workloads.
        64MB cache improves performance for frequently accessed data.
        """
        try:
            self._conn = sqlite3.connect(
                str(DB_PATH),
                check_same_thread=False,
                timeout=DB_CONNECTION_TIMEOUT,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
            self._conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT}")
            self._conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            logger.error("Database Connection Failed", [("Error", str(e))])
            raise

    def _ensure_connection(self) -> sqlite3.Connection:
        """Ensure connection is valid, reconnect if needed."""
        if self._conn is None:
            self._connect()
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error:
            self._connect()
        return self._conn

    def execute(
        self,
        query: str,
        params: Tuple = (),
        commit: bool = True
    ) -> sqlite3.Cursor:
        """Execute a query with thread safety."""
        with self._db_lock:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            if commit:
                conn.commit()
            return cursor

    def executemany(
        self,
        query: str,
        params_list: List[Tuple],
        commit: bool = True
    ) -> sqlite3.Cursor:
        """Execute many queries with thread safety."""
        with self._db_lock:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            if commit:
                conn.commit()
            return cursor

    def fetchone(self, query: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        """Execute query and fetch one result."""
        cursor = self.execute(query, params, commit=False)
        return cursor.fetchone()

    def fetchall(self, query: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """Execute query and fetch all results."""
        cursor = self.execute(query, params, commit=False)
        return cursor.fetchall()

    def close(self) -> None:
        """Close database connection."""
        with self._db_lock:
            if self._conn:
                self._conn.close()
                self._conn = None
                logger.info("Database Connection Closed")

    # =========================================================================
    # Transaction Support
    # =========================================================================

    class Transaction:
        """
        Context manager for atomic database transactions.

        Usage:
            with db.transaction() as tx:
                tx.execute("INSERT INTO ...", (...))
                tx.execute("UPDATE ...", (...))
            # Commits on success, rolls back on exception
        """

        def __init__(self, db: "DatabaseManager"):
            self._db = db
            self._cursor: Optional[sqlite3.Cursor] = None

        def __enter__(self) -> "DatabaseManager.Transaction":
            self._db._db_lock.acquire()
            conn = self._db._ensure_connection()
            conn.execute("BEGIN IMMEDIATE")
            self._cursor = conn.cursor()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
            conn = self._db._ensure_connection()
            try:
                if exc_type is None:
                    conn.commit()
                else:
                    conn.rollback()
                    logger.warning("Database Transaction Rolled Back", [
                        ("Error", str(exc_val)[:100] if exc_val else "Unknown"),
                    ])
            finally:
                self._db._db_lock.release()
            return False  # Don't suppress exceptions

        def execute(self, query: str, params: Tuple = ()) -> sqlite3.Cursor:
            """Execute a query within this transaction."""
            self._cursor.execute(query, params)
            return self._cursor

        def fetchone(self) -> Optional[sqlite3.Row]:
            """Fetch one result from the last query."""
            return self._cursor.fetchone() if self._cursor else None

        def fetchall(self) -> List[sqlite3.Row]:
            """Fetch all results from the last query."""
            return self._cursor.fetchall() if self._cursor else []

        @property
        def lastrowid(self) -> int:
            """Get the last inserted row ID."""
            return self._cursor.lastrowid if self._cursor else 0

    def transaction(self) -> "DatabaseManager.Transaction":
        """
        Create a new transaction context manager.

        Returns:
            Transaction context manager for atomic operations.

        Example:
            with db.transaction() as tx:
                tx.execute("INSERT INTO users ...", (user_id,))
                tx.execute("INSERT INTO logs ...", (user_id, action))
            # Both inserts succeed or both are rolled back
        """
        return self.Transaction(self)

    # =========================================================================
    # Extend Mute Operation (uses MutesMixin data)
    # =========================================================================

    def extend_mute(
        self,
        user_id: int,
        guild_id: int,
        additional_seconds: int,
        moderator_id: int,
        reason: Optional[str] = None,
    ) -> Optional[float]:
        """
        Extend an active mute by additional duration.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            additional_seconds: Additional time to add.
            moderator_id: Moderator extending the mute.
            reason: Optional reason for extension.

        Returns:
            New expiration timestamp, or None if no active mute.
        """
        now = time.time()

        # Get current mute
        row = self.fetchone(
            """SELECT id, expires_at FROM active_mutes
               WHERE user_id = ? AND guild_id = ? AND unmuted = 0""",
            (user_id, guild_id)
        )

        if not row:
            return None

        # Calculate new expiration
        current_expires = row["expires_at"]
        if current_expires is None:
            # Permanent mute, can't extend
            return None

        new_expires = current_expires + additional_seconds

        # Use transaction for atomicity - both UPDATE and INSERT succeed or both fail
        with self.transaction() as tx:
            # Update the mute
            tx.execute(
                "UPDATE active_mutes SET expires_at = ? WHERE id = ?",
                (new_expires, row["id"])
            )

            # Log to history
            tx.execute(
                """INSERT INTO mute_history
                   (user_id, guild_id, moderator_id, action, reason, duration_seconds, timestamp)
                   VALUES (?, ?, ?, 'extend', ?, ?, ?)""",
                (user_id, guild_id, moderator_id, reason, additional_seconds, now)
            )

        # Format duration for logging
        hours, remainder = divmod(additional_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        duration_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

        logger.tree("MUTE EXTENDED", [
            ("User ID", str(user_id)),
            ("Extension", duration_str),
            ("Moderator ID", str(moderator_id)),
            ("Reason", (reason[:30] + "...") if reason and len(reason) > 30 else (reason or "None")),
        ], emoji="⏱️")

        return new_expires


# =============================================================================
# Global Instance
# =============================================================================

def get_db() -> DatabaseManager:
    """Get the global database manager instance."""
    return DatabaseManager()


# Legacy alias for backwards compatibility
Database = DatabaseManager


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DatabaseManager", "Database", "get_db", "DB_PATH", "DATA_DIR"]
