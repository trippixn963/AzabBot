"""
Azab Discord Bot - Unified Database
====================================

Central SQLite database manager for all bot data.

Consolidates:
- Bot state (active/disabled)
- Ignored users list
- Prisoner tracking and statistics
- Message logging
- Roast history

Single database file: data/azab.db

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
import threading
import asyncio
import time
import secrets
import string
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple, Any, Set, Dict, TypedDict

from src.core.logger import logger


# =============================================================================
# Type Definitions
# =============================================================================

class MuteRecord(TypedDict, total=False):
    """Type for mute records returned from database."""
    id: int
    user_id: int
    guild_id: int
    muted_at: float
    duration_minutes: Optional[int]
    reason: Optional[str]
    moderator_id: Optional[int]
    unmuted_at: Optional[float]


class CaseLogRecord(TypedDict, total=False):
    """Type for case log records."""
    id: int
    case_id: str
    user_id: int
    thread_id: int
    profile_message_id: Optional[int]
    created_at: float


class TrackedModRecord(TypedDict, total=False):
    """Type for tracked mod records."""
    id: int
    mod_id: int
    thread_id: int
    added_at: float


class AltLinkRecord(TypedDict, total=False):
    """Type for alt link records."""
    id: int
    banned_user_id: int
    potential_alt_id: int
    guild_id: int
    confidence: str
    total_score: int
    signals: str
    detected_at: float
    reviewed: int


class JoinInfoRecord(TypedDict, total=False):
    """Type for user join info records."""
    user_id: int
    guild_id: int
    invite_code: Optional[str]
    inviter_id: Optional[int]
    joined_at: float
    avatar_hash: Optional[str]


class MemberActivityRecord(TypedDict, total=False):
    """Type for member activity records."""
    user_id: int
    guild_id: int
    join_count: int
    last_join: float
    message_count: int
    last_message: Optional[float]


class PendingReasonRecord(TypedDict, total=False):
    """Type for pending reason records."""
    id: int
    thread_id: int
    moderator_id: int
    action_type: str
    created_at: float


from src.core.config import NY_TZ
from src.utils.metrics import metrics


# =============================================================================
# Constants
# =============================================================================

DATA_DIR: Path = Path(__file__).parent.parent.parent / "data"
DB_PATH: Path = DATA_DIR / "azab.db"


# =============================================================================
# Database Manager (Singleton)
# =============================================================================

class DatabaseManager:
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
                timeout=30.0,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA foreign_keys=ON")
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
    # Table Initialization
    # =========================================================================

    def _init_tables(self) -> None:
        """
        Initialize all database tables.

        DESIGN: Tables are created if not exist, allowing safe restarts.
        Indexes added for frequently queried columns.
        """
        conn = self._ensure_connection()
        cursor = conn.cursor()

        # -----------------------------------------------------------------
        # Bot State Table (replaces bot_state.json)
        # DESIGN: Key-value store for bot configuration
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        # -----------------------------------------------------------------
        # Ignored Users Table (replaces ignored_users.json)
        # DESIGN: Users the bot will not respond to
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ignored_users (
                user_id INTEGER PRIMARY KEY,
                added_at REAL NOT NULL
            )
        """)

        # -----------------------------------------------------------------
        # Users Table
        # DESIGN: Tracks all users who have interacted with bot
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                messages_count INTEGER DEFAULT 0,
                is_imprisoned BOOLEAN DEFAULT 0
            )
        """)

        # -----------------------------------------------------------------
        # Messages Table
        # DESIGN: Logs messages for AI context
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                content TEXT,
                channel_id INTEGER,
                guild_id INTEGER,
                timestamp TEXT
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)"
        )

        # -----------------------------------------------------------------
        # Prisoner History Table
        # DESIGN: Complete history of all mutes/unmutes
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prisoner_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                mute_reason TEXT,
                trigger_message TEXT,
                muted_at TEXT,
                unmuted_at TEXT,
                duration_minutes INTEGER,
                muted_by TEXT,
                unmuted_by TEXT,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_prisoner_user ON prisoner_history(user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_prisoner_active ON prisoner_history(is_active)"
        )

        # -----------------------------------------------------------------
        # Roast History Table
        # DESIGN: Tracks AI-generated roasts to avoid repetition
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roast_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                roast_text TEXT,
                roast_category TEXT,
                timestamp TEXT,
                mute_session_id INTEGER,
                FOREIGN KEY (mute_session_id) REFERENCES prisoner_history(id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_roast_user ON roast_history(user_id)"
        )

        # -----------------------------------------------------------------
        # User Profiles Table
        # DESIGN: AI personalization data
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                favorite_excuse TEXT,
                most_used_words TEXT,
                personality_type TEXT,
                total_roasts_received INTEGER DEFAULT 0,
                last_roast_time TEXT,
                callback_references TEXT
            )
        """)

        # -----------------------------------------------------------------
        # Active Mutes Table
        # DESIGN: Tracks currently muted users for auto-unmute scheduler
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_mutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                muted_at REAL NOT NULL,
                expires_at REAL,
                unmuted INTEGER DEFAULT 0,
                UNIQUE(user_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_mutes_expires ON active_mutes(expires_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_mutes_user ON active_mutes(user_id, guild_id)"
        )
        # Composite index for efficient expired mute lookups
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_mutes_search ON active_mutes(guild_id, unmuted, expires_at)"
        )

        # -----------------------------------------------------------------
        # Mute History Table
        # DESIGN: Complete log of all mute/unmute actions for modlog
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mute_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                duration_seconds INTEGER,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mute_history_user ON mute_history(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mute_history_time ON mute_history(timestamp)"
        )

        # -----------------------------------------------------------------
        # Case Logs Table
        # DESIGN: Tracks unique case threads per user in mods forum
        # case_id is a 4-character alphanumeric code (e.g., "A7X2")
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS case_logs (
                user_id INTEGER PRIMARY KEY,
                case_id TEXT UNIQUE NOT NULL,
                thread_id INTEGER NOT NULL,
                mute_count INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                last_mute_at REAL,
                last_unmute_at REAL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_case_logs_case_id ON case_logs(case_id)"
        )

        # Migration: Add ban tracking columns if they don't exist
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN ban_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN last_ban_at REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN profile_message_id INTEGER")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # -----------------------------------------------------------------
        # Mod Tracker Table
        # DESIGN: Tracks moderators and their activity log threads
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mod_tracker (
                mod_id INTEGER PRIMARY KEY,
                thread_id INTEGER NOT NULL,
                display_name TEXT,
                avatar_hash TEXT,
                username TEXT,
                created_at REAL NOT NULL
            )
        """)

        # -----------------------------------------------------------------
        # Nickname History Table
        # DESIGN: Tracks all past nicknames for users
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nickname_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                old_nickname TEXT,
                new_nickname TEXT,
                changed_by INTEGER,
                changed_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nickname_user ON nickname_history(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nickname_time ON nickname_history(changed_at)"
        )

        # -----------------------------------------------------------------
        # Member Activity Table
        # DESIGN: Tracks join/leave counts for members
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS member_activity (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                join_count INTEGER DEFAULT 0,
                leave_count INTEGER DEFAULT 0,
                first_joined_at REAL,
                last_joined_at REAL,
                last_left_at REAL,
                PRIMARY KEY (user_id, guild_id)
            )
        """)

        # -----------------------------------------------------------------
        # Pending Reasons Table
        # DESIGN: Tracks mod actions awaiting reason replies
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_reasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                warning_message_id INTEGER NOT NULL,
                embed_message_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                created_at REAL NOT NULL,
                owner_notified INTEGER DEFAULT 0
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_reasons_thread ON pending_reasons(thread_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_reasons_created ON pending_reasons(created_at)"
        )

        # -----------------------------------------------------------------
        # Alt Links Table
        # DESIGN: Stores detected alt account relationships
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alt_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                banned_user_id INTEGER NOT NULL,
                potential_alt_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                confidence TEXT NOT NULL,
                total_score INTEGER NOT NULL,
                signals TEXT NOT NULL,
                detected_at REAL NOT NULL,
                reviewed INTEGER DEFAULT 0,
                reviewed_by INTEGER,
                reviewed_at REAL,
                UNIQUE(banned_user_id, potential_alt_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alt_links_banned ON alt_links(banned_user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_alt_links_alt ON alt_links(potential_alt_id)"
        )

        # -----------------------------------------------------------------
        # User Join Info Table
        # DESIGN: Stores invite/join data for alt detection
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_join_info (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                invite_code TEXT,
                inviter_id INTEGER,
                joined_at REAL NOT NULL,
                avatar_hash TEXT,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_join_inviter ON user_join_info(inviter_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_join_avatar ON user_join_info(avatar_hash)"
        )

        conn.commit()

    # =========================================================================
    # Bot State Operations
    # =========================================================================

    def get_bot_state(self, key: str, default: Any = None) -> Any:
        """
        Get a bot state value.

        Args:
            key: State key to retrieve
            default: Default value if key not found

        Returns:
            Stored value or default
        """
        import json
        row = self.fetchone("SELECT value FROM bot_state WHERE key = ?", (key,))
        if row:
            try:
                return json.loads(row["value"])
            except json.JSONDecodeError:
                return row["value"]
        return default

    def set_bot_state(self, key: str, value: Any) -> None:
        """
        Set a bot state value.

        Args:
            key: State key to set
            value: Value to store (will be JSON encoded)
        """
        import json
        value_str = json.dumps(value) if not isinstance(value, str) else value
        self.execute(
            "INSERT OR REPLACE INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value_str, time.time())
        )

    def is_active(self) -> bool:
        """Check if bot is active (not disabled)."""
        return self.get_bot_state("is_active", True)

    def set_active(self, active: bool) -> None:
        """
        Set bot active state.

        Args:
            active: True to enable, False to disable
        """
        self.set_bot_state("is_active", active)
        logger.tree("Bot State Changed", [
            ("Active", str(active)),
        ], emoji="⚙️")

    # =========================================================================
    # Ignored Users Operations
    # =========================================================================

    def get_ignored_users(self) -> Set[int]:
        """Get set of ignored user IDs."""
        rows = self.fetchall("SELECT user_id FROM ignored_users")
        return {row["user_id"] for row in rows}

    def add_ignored_user(self, user_id: int) -> None:
        """Add a user to ignored list."""
        self.execute(
            "INSERT OR IGNORE INTO ignored_users (user_id, added_at) VALUES (?, ?)",
            (user_id, time.time())
        )
        logger.tree("User Added to Ignore List", [
            ("User ID", str(user_id)),
        ], emoji="🚫")

    def remove_ignored_user(self, user_id: int) -> None:
        """Remove a user from ignored list."""
        self.execute("DELETE FROM ignored_users WHERE user_id = ?", (user_id,))
        logger.tree("User Removed from Ignore List", [
            ("User ID", str(user_id)),
        ], emoji="✅")

    def is_user_ignored(self, user_id: int) -> bool:
        """Check if a user is ignored."""
        row = self.fetchone(
            "SELECT 1 FROM ignored_users WHERE user_id = ?",
            (user_id,)
        )
        return row is not None

    # =========================================================================
    # Message Logging
    # =========================================================================

    async def log_message(
        self,
        user_id: int,
        username: str,
        content: str,
        channel_id: int,
        guild_id: int,
    ) -> None:
        """
        Log a message to the database.

        DESIGN: Runs in thread to avoid blocking event loop.
        Content truncated to 500 chars for storage efficiency.
        """
        def _log():
            timestamp = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            truncated = content[:500] if content else ""

            self.execute(
                "INSERT OR REPLACE INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            self.execute(
                """INSERT INTO messages
                   (user_id, content, channel_id, guild_id, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, truncated, channel_id, guild_id, timestamp)
            )
            self.execute(
                "UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?",
                (user_id,)
            )

        await asyncio.to_thread(_log)

    # =========================================================================
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

    async def record_unmute(self, user_id: int, unmuted_by: Optional[str] = None) -> None:
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

    async def get_current_mute_duration(self, user_id: int) -> int:
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

    async def get_prisoner_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Get comprehensive prisoner stats in a single optimized query.

        Returns:
            Dict with total_mutes, total_minutes, last_mute, etc.
        """
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

        return await asyncio.to_thread(_get)

    async def get_current_mute_session_id(self, user_id: int) -> Optional[int]:
        """Get current active mute session ID."""
        def _get():
            row = self.fetchone(
                "SELECT id FROM prisoner_history WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            return row["id"] if row else None

        return await asyncio.to_thread(_get)

    # =========================================================================
    # Roast History
    # =========================================================================

    async def save_roast(
        self,
        user_id: int,
        roast_text: str,
        category: str = "general",
        session_id: Optional[int] = None,
    ) -> None:
        """
        Save a roast to history.

        DESIGN: Tracks roasts to avoid repetition in AI generation.
        """
        def _save():
            timestamp = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            self.execute(
                """INSERT INTO roast_history
                   (user_id, roast_text, roast_category, timestamp, mute_session_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, roast_text[:500], category, timestamp, session_id)
            )

            self.execute(
                """INSERT INTO user_profiles (user_id, total_roasts_received, last_roast_time)
                   VALUES (?, 1, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   total_roasts_received = total_roasts_received + 1,
                   last_roast_time = ?""",
                (user_id, timestamp, timestamp)
            )

        await asyncio.to_thread(_save)

    async def get_recent_roasts(self, user_id: int, limit: int = 5) -> List[str]:
        """
        Get recent roasts for a user.

        Args:
            user_id: User to get roasts for
            limit: Maximum number of roasts to return

        Returns:
            List of recent roast texts
        """
        def _get():
            rows = self.fetchall(
                "SELECT roast_text FROM roast_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            )
            return [row["roast_text"] for row in rows]

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

    def is_user_muted(self, user_id: int, guild_id: int) -> bool:
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

    def get_expired_mutes(self) -> List[sqlite3.Row]:
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

    def get_all_active_mutes(self, guild_id: Optional[int] = None) -> List[sqlite3.Row]:
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

    def get_user_mute_count(self, user_id: int, guild_id: int) -> int:
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

    def get_mute_moderator_ids(self, user_id: int, guild_id: int) -> List[int]:
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
    # Case Log Operations
    # =========================================================================

    def get_next_case_id(self) -> str:
        """
        Generate a unique 4-character alphanumeric case ID.

        DESIGN:
            Uses uppercase letters and digits for readability.
            Checks database to ensure uniqueness before returning.
            With 36^4 = 1,679,616 possible combinations, collisions are rare.

        Returns:
            Unique 4-character case ID (e.g., "A7X2", "K3M9").
        """
        chars = string.ascii_uppercase + string.digits  # A-Z, 0-9

        while True:
            # Generate random 4-character code
            case_id = ''.join(secrets.choice(chars) for _ in range(4))

            # Check if it already exists
            row = self.fetchone(
                "SELECT 1 FROM case_logs WHERE case_id = ?",
                (case_id,)
            )

            if not row:
                return case_id

    def get_case_log(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get case log for a user.

        Args:
            user_id: Discord user ID.

        Returns:
            Case log dict or None if no case exists.
        """
        row = self.fetchone(
            "SELECT * FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        if row:
            return dict(row)
        return None

    def create_case_log(
        self,
        user_id: int,
        case_id: str,
        thread_id: int,
    ) -> None:
        """
        Create a new case log for a user.

        Args:
            user_id: Discord user ID.
            case_id: Unique 4-character alphanumeric case ID.
            thread_id: Forum thread ID for this case.
        """
        now = time.time()
        self.execute(
            """INSERT INTO case_logs
               (user_id, case_id, thread_id, mute_count, created_at, last_mute_at)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (user_id, case_id, thread_id, now, now)
        )

        logger.tree("Case Log Created", [
            ("User ID", str(user_id)),
            ("Case ID", case_id),
            ("Thread ID", str(thread_id)),
        ], emoji="📋")

    def increment_mute_count(self, user_id: int) -> int:
        """
        Increment mute count for a user's case.

        Args:
            user_id: Discord user ID.

        Returns:
            New mute count.
        """
        now = time.time()
        self.execute(
            """UPDATE case_logs
               SET mute_count = mute_count + 1, last_mute_at = ?
               WHERE user_id = ?""",
            (now, user_id)
        )

        row = self.fetchone(
            "SELECT mute_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        return row["mute_count"] if row else 1

    def update_last_unmute(self, user_id: int) -> None:
        """
        Update last unmute timestamp for a user's case.

        Args:
            user_id: Discord user ID.
        """
        now = time.time()
        self.execute(
            "UPDATE case_logs SET last_unmute_at = ? WHERE user_id = ?",
            (now, user_id)
        )

    def increment_ban_count(self, user_id: int) -> int:
        """
        Increment ban count for a user's case.

        Args:
            user_id: Discord user ID.

        Returns:
            New ban count.
        """
        now = time.time()
        self.execute(
            """UPDATE case_logs
               SET ban_count = COALESCE(ban_count, 0) + 1, last_ban_at = ?
               WHERE user_id = ?""",
            (now, user_id)
        )

        row = self.fetchone(
            "SELECT ban_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        return row["ban_count"] if row and row["ban_count"] else 1

    def get_user_ban_count(self, user_id: int, guild_id: int) -> int:
        """
        Get total number of bans for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID (unused, for API consistency).

        Returns:
            Total ban count.
        """
        row = self.fetchone(
            "SELECT ban_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        return row["ban_count"] if row and row["ban_count"] else 0

    def get_all_case_logs(self) -> List[Dict[str, Any]]:
        """
        Get all case logs.

        Returns:
            List of all case log dicts.
        """
        rows = self.fetchall("SELECT * FROM case_logs ORDER BY case_id")
        return [dict(row) for row in rows]

    def set_profile_message_id(self, user_id: int, message_id: int) -> None:
        """
        Set the profile message ID for a case.

        Args:
            user_id: Discord user ID.
            message_id: The message ID of the pinned profile.
        """
        self.execute(
            "UPDATE case_logs SET profile_message_id = ? WHERE user_id = ?",
            (message_id, user_id)
        )

    # =========================================================================
    # Mod Tracker Operations
    # =========================================================================

    def get_tracked_mod(self, mod_id: int) -> Optional[Dict[str, Any]]:
        """
        Get tracked mod info.

        Args:
            mod_id: Discord user ID of the mod.

        Returns:
            Dict with mod tracker info or None if not tracked.
        """
        row = self.fetchone(
            "SELECT * FROM mod_tracker WHERE mod_id = ?",
            (mod_id,)
        )
        return dict(row) if row else None

    def add_tracked_mod(
        self,
        mod_id: int,
        thread_id: int,
        display_name: str,
        username: str,
        avatar_hash: Optional[str] = None,
    ) -> None:
        """
        Add a mod to the tracker.

        Args:
            mod_id: Discord user ID.
            thread_id: Forum thread ID for their activity log.
            display_name: Current display name.
            username: Current username.
            avatar_hash: Current avatar hash for change detection.
        """
        now = time.time()
        self.execute(
            """INSERT OR REPLACE INTO mod_tracker
               (mod_id, thread_id, display_name, avatar_hash, username, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (mod_id, thread_id, display_name, avatar_hash, username, now)
        )

    def remove_tracked_mod(self, mod_id: int) -> bool:
        """
        Remove a mod from the tracker.

        Args:
            mod_id: Discord user ID.

        Returns:
            True if mod was removed, False if not found.
        """
        row = self.fetchone(
            "SELECT mod_id FROM mod_tracker WHERE mod_id = ?",
            (mod_id,)
        )
        if row:
            self.execute("DELETE FROM mod_tracker WHERE mod_id = ?", (mod_id,))
            return True
        return False

    def get_all_tracked_mods(self) -> List[Dict[str, Any]]:
        """
        Get all tracked mods.

        Returns:
            List of all tracked mod dicts.
        """
        rows = self.fetchall("SELECT * FROM mod_tracker")
        return [dict(row) for row in rows]

    def update_mod_info(
        self,
        mod_id: int,
        display_name: Optional[str] = None,
        username: Optional[str] = None,
        avatar_hash: Optional[str] = None,
    ) -> None:
        """
        Update stored mod info for change detection.

        Args:
            mod_id: Discord user ID.
            display_name: New display name (if changed).
            username: New username (if changed).
            avatar_hash: New avatar hash (if changed).
        """
        updates = []
        params = []

        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
        if username is not None:
            updates.append("username = ?")
            params.append(username)
        if avatar_hash is not None:
            updates.append("avatar_hash = ?")
            params.append(avatar_hash)

        if updates:
            params.append(mod_id)
            self.execute(
                f"UPDATE mod_tracker SET {', '.join(updates)} WHERE mod_id = ?",
                tuple(params)
            )

    # =========================================================================
    # Nickname History Operations
    # =========================================================================

    def save_nickname_change(
        self,
        user_id: int,
        guild_id: int,
        old_nickname: Optional[str],
        new_nickname: Optional[str],
        changed_by: Optional[int] = None,
    ) -> None:
        """
        Save a nickname change to history.

        Args:
            user_id: Discord user ID whose nickname changed.
            guild_id: Guild where the change occurred.
            old_nickname: Previous nickname (None if no nickname).
            new_nickname: New nickname (None if cleared).
            changed_by: User ID who made the change (None if self).
        """
        now = time.time()
        self.execute(
            """INSERT INTO nickname_history
               (user_id, guild_id, old_nickname, new_nickname, changed_by, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, old_nickname, new_nickname, changed_by, now)
        )

    def get_nickname_history(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get nickname history for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.

        Returns:
            List of nickname history records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM nickname_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY changed_at DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

    def get_all_nicknames(
        self,
        user_id: int,
        guild_id: int,
    ) -> List[str]:
        """
        Get all unique nicknames a user has had.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            List of unique nicknames (excluding None).
        """
        rows = self.fetchall(
            """SELECT DISTINCT old_nickname FROM nickname_history
               WHERE user_id = ? AND guild_id = ? AND old_nickname IS NOT NULL
               UNION
               SELECT DISTINCT new_nickname FROM nickname_history
               WHERE user_id = ? AND guild_id = ? AND new_nickname IS NOT NULL""",
            (user_id, guild_id, user_id, guild_id)
        )
        return [row["old_nickname"] or row["new_nickname"] for row in rows if row[0]]

    # =========================================================================
    # Member Activity Operations
    # =========================================================================

    def record_member_join(self, user_id: int, guild_id: int) -> int:
        """
        Record a member join and return their join count.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            The member's total join count (including this one).
        """
        now = time.time()
        # Insert or update the member activity record
        self.execute(
            """INSERT INTO member_activity (user_id, guild_id, join_count, first_joined_at, last_joined_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET
                   join_count = join_count + 1,
                   last_joined_at = ?""",
            (user_id, guild_id, now, now, now)
        )
        # Get the updated count
        row = self.fetchone(
            "SELECT join_count FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["join_count"] if row else 1

    def record_member_leave(self, user_id: int, guild_id: int) -> int:
        """
        Record a member leave and return their leave count.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            The member's total leave count (including this one).
        """
        now = time.time()
        # Insert or update the member activity record
        self.execute(
            """INSERT INTO member_activity (user_id, guild_id, leave_count, last_left_at)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET
                   leave_count = leave_count + 1,
                   last_left_at = ?""",
            (user_id, guild_id, now, now)
        )
        # Get the updated count
        row = self.fetchone(
            "SELECT leave_count FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["leave_count"] if row else 1

    def get_member_activity(self, user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a member's join/leave activity.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Dict with join_count, leave_count, first_joined_at, last_joined_at, last_left_at
            or None if no record exists.
        """
        row = self.fetchone(
            "SELECT * FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    # =========================================================================
    # Pending Reasons Operations
    # =========================================================================

    def create_pending_reason(
        self,
        thread_id: int,
        warning_message_id: int,
        embed_message_id: int,
        moderator_id: int,
        target_user_id: int,
        action_type: str,
    ) -> int:
        """
        Create a pending reason request.

        Args:
            thread_id: Case thread ID.
            warning_message_id: ID of the warning message to delete when resolved.
            embed_message_id: ID of the embed to update with reason.
            moderator_id: Moderator who needs to provide reason.
            target_user_id: User the action was taken against.
            action_type: Type of action (mute, ban, etc).

        Returns:
            ID of the created pending reason.
        """
        return self.execute(
            """
            INSERT INTO pending_reasons
            (thread_id, warning_message_id, embed_message_id, moderator_id, target_user_id, action_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (thread_id, warning_message_id, embed_message_id, moderator_id, target_user_id, action_type, time.time())
        )

    def get_pending_reason_by_thread(self, thread_id: int, moderator_id: int) -> Optional[Dict]:
        """
        Get pending reason for a thread and moderator.

        Args:
            thread_id: Case thread ID.
            moderator_id: Moderator ID.

        Returns:
            Pending reason record or None.
        """
        row = self.fetchone(
            """
            SELECT * FROM pending_reasons
            WHERE thread_id = ? AND moderator_id = ? AND owner_notified = 0
            ORDER BY created_at DESC LIMIT 1
            """,
            (thread_id, moderator_id)
        )
        return dict(row) if row else None

    def get_expired_pending_reasons(self, max_age_seconds: int = 3600) -> List[Dict]:
        """
        Get pending reasons older than max_age_seconds that haven't been resolved.

        Args:
            max_age_seconds: Maximum age in seconds (default 1 hour).

        Returns:
            List of expired pending reason records.
        """
        cutoff = time.time() - max_age_seconds
        rows = self.fetchall(
            """
            SELECT * FROM pending_reasons
            WHERE created_at < ? AND owner_notified = 0
            """,
            (cutoff,)
        )
        return [dict(row) for row in rows]

    def mark_pending_reason_notified(self, pending_id: int) -> None:
        """Mark a pending reason as owner notified."""
        self.execute(
            "UPDATE pending_reasons SET owner_notified = 1 WHERE id = ?",
            (pending_id,)
        )

    def delete_pending_reason(self, pending_id: int) -> None:
        """Delete a pending reason (when resolved)."""
        self.execute(
            "DELETE FROM pending_reasons WHERE id = ?",
            (pending_id,)
        )

    def delete_pending_reasons_for_thread(self, thread_id: int, moderator_id: int) -> None:
        """Delete all pending reasons for a thread and moderator."""
        self.execute(
            "DELETE FROM pending_reasons WHERE thread_id = ? AND moderator_id = ?",
            (thread_id, moderator_id)
        )

    def cleanup_old_pending_reasons(self, max_age_seconds: int = 86400) -> int:
        """
        Delete old pending reasons that have been notified.

        Args:
            max_age_seconds: Maximum age in seconds (default 24 hours).

        Returns:
            Number of records deleted.
        """
        cutoff = time.time() - max_age_seconds
        return self.execute(
            "DELETE FROM pending_reasons WHERE owner_notified = 1 AND created_at < ?",
            (cutoff,)
        )

    # =========================================================================
    # Alt Detection Operations
    # =========================================================================

    def save_alt_link(
        self,
        banned_user_id: int,
        potential_alt_id: int,
        guild_id: int,
        confidence: str,
        total_score: int,
        signals: dict,
    ) -> int:
        """
        Save a detected alt link to the database.

        Args:
            banned_user_id: The banned user's ID.
            potential_alt_id: The potential alt account's ID.
            guild_id: The guild ID.
            confidence: Confidence level (LOW, MEDIUM, HIGH).
            total_score: Total detection score.
            signals: Dictionary of matched signals.

        Returns:
            The row ID of the inserted record.
        """
        import json
        signals_json = json.dumps(signals)
        cursor = self.execute(
            """
            INSERT OR REPLACE INTO alt_links
            (banned_user_id, potential_alt_id, guild_id, confidence, total_score, signals, detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (banned_user_id, potential_alt_id, guild_id, confidence, total_score, signals_json, time.time())
        )
        return cursor.lastrowid

    def get_alt_links_for_user(self, user_id: int, guild_id: int) -> List[Dict]:
        """
        Get all potential alts linked to a user.

        Args:
            user_id: The banned user's ID.
            guild_id: The guild ID.

        Returns:
            List of alt link records.
        """
        import json
        rows = self.fetchall(
            "SELECT * FROM alt_links WHERE banned_user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        results = []
        for row in rows:
            record = dict(row)
            record['signals'] = json.loads(record['signals'])
            results.append(record)
        return results

    def get_users_linked_to_alt(self, alt_id: int, guild_id: int) -> List[Dict]:
        """
        Get all users that have this account flagged as an alt.

        Args:
            alt_id: The potential alt's ID.
            guild_id: The guild ID.

        Returns:
            List of alt link records.
        """
        import json
        rows = self.fetchall(
            "SELECT * FROM alt_links WHERE potential_alt_id = ? AND guild_id = ?",
            (alt_id, guild_id)
        )
        results = []
        for row in rows:
            record = dict(row)
            record['signals'] = json.loads(record['signals'])
            results.append(record)
        return results

    def mark_alt_link_reviewed(
        self,
        link_id: int,
        reviewer_id: int,
        confirmed: bool
    ) -> None:
        """
        Mark an alt link as reviewed.

        Args:
            link_id: The alt link record ID.
            reviewer_id: The moderator who reviewed it.
            confirmed: True if confirmed alt, False if false positive.
        """
        status = 1 if confirmed else 2  # 1 = confirmed, 2 = false positive
        self.execute(
            "UPDATE alt_links SET reviewed = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewer_id, time.time(), link_id)
        )

    # =========================================================================
    # User Join Info Operations
    # =========================================================================

    def save_user_join_info(
        self,
        user_id: int,
        guild_id: int,
        invite_code: Optional[str],
        inviter_id: Optional[int],
        joined_at: float,
        avatar_hash: Optional[str],
    ) -> None:
        """
        Save user join information for alt detection.

        Args:
            user_id: The user's ID.
            guild_id: The guild ID.
            invite_code: The invite code used (if known).
            inviter_id: The inviter's ID (if known).
            joined_at: Timestamp of when they joined.
            avatar_hash: Hash of their avatar (if any).
        """
        self.execute(
            """
            INSERT OR REPLACE INTO user_join_info
            (user_id, guild_id, invite_code, inviter_id, joined_at, avatar_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, guild_id, invite_code, inviter_id, joined_at, avatar_hash)
        )

    def get_user_join_info(self, user_id: int, guild_id: int) -> Optional[Dict]:
        """
        Get join information for a user.

        Args:
            user_id: The user's ID.
            guild_id: The guild ID.

        Returns:
            Join info dict or None.
        """
        row = self.fetchone(
            "SELECT * FROM user_join_info WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    def get_users_by_inviter(self, inviter_id: int, guild_id: int) -> List[Dict]:
        """
        Get all users invited by a specific person.

        Args:
            inviter_id: The inviter's ID.
            guild_id: The guild ID.

        Returns:
            List of user join info records.
        """
        rows = self.fetchall(
            "SELECT * FROM user_join_info WHERE inviter_id = ? AND guild_id = ?",
            (inviter_id, guild_id)
        )
        return [dict(row) for row in rows]

    def get_users_by_avatar_hash(self, avatar_hash: str, guild_id: int) -> List[Dict]:
        """
        Get all users with a specific avatar hash.

        Args:
            avatar_hash: The avatar hash to search for.
            guild_id: The guild ID.

        Returns:
            List of user join info records.
        """
        rows = self.fetchall(
            "SELECT * FROM user_join_info WHERE avatar_hash = ? AND guild_id = ?",
            (avatar_hash, guild_id)
        )
        return [dict(row) for row in rows]


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
