"""
AzabBot - Database Base Module
==============================

Core database connection and execution methods.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import sqlite3
import threading
import asyncio
from pathlib import Path
from typing import Optional, List, Tuple, Any, Dict

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "azab.db"


# =============================================================================
# Helper Functions
# =============================================================================

def _safe_json_loads(value: Optional[str], default: Any = None) -> Any:
    """Safely parse JSON, returning default on error."""
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"Corrupted JSON in database: {value[:50] if len(value) > 50 else value}")
        return default if default is not None else []


# =============================================================================
# Base Database Class
# =============================================================================

class DatabaseBase:
    """
    Base database manager with connection and execution methods.

    DESIGN: Provides thread-safe database operations.
    Uses WAL mode for better concurrency.
    """

    _instance: Optional["DatabaseBase"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "DatabaseBase":
        """Singleton pattern - only one instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def _init_base(self) -> None:
        """Initialize base database components."""
        self._db_lock: threading.Lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

        # Cache for expensive queries (TTL-based)
        self._prisoner_stats_cache: Dict[int, tuple] = {}
        self._prisoner_stats_ttl: int = 60
        self._prisoner_stats_lock = asyncio.Lock()

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._connect()

    # =========================================================================
    # Connection Management
    # =========================================================================

    def _connect(self) -> None:
        """Establish database connection with WAL mode."""
        try:
            self._conn = sqlite3.connect(
                str(DB_PATH),
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA mmap_size=268435456")
            self._conn.execute("PRAGMA busy_timeout=5000")
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
        """Context manager for atomic database transactions."""

        def __init__(self, db: "DatabaseBase"):
            self._db = db
            self._cursor: Optional[sqlite3.Cursor] = None

        def __enter__(self) -> "DatabaseBase.Transaction":
            self._db._db_lock.acquire()
            conn = self._db._ensure_connection()
            conn.execute("BEGIN IMMEDIATE")
            self._cursor = conn.cursor()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
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
            return False

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

    def transaction(self) -> "DatabaseBase.Transaction":
        """Create a new transaction context manager."""
        return self.Transaction(self)
