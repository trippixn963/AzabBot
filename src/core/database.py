"""
Azab Discord Bot - Unified Database
====================================

Central SQLite database manager for all bot data.

Consolidates:
- Bot state (active/disabled)
- Ignored users list
- Prisoner tracking and statistics
- Message logging

Single database file: data/azab.db

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
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


class ModNoteRecord(TypedDict, total=False):
    """Type for moderator note records."""
    id: int
    user_id: int
    guild_id: int
    moderator_id: int
    note: str
    created_at: float


class UsernameHistoryRecord(TypedDict, total=False):
    """Type for username history records."""
    id: int
    user_id: int
    username: Optional[str]
    display_name: Optional[str]
    guild_id: Optional[int]
    changed_at: float


class AppealRecord(TypedDict, total=False):
    """Type for appeal records."""
    id: int
    appeal_id: str
    case_id: str
    user_id: int
    guild_id: int
    thread_id: int
    action_type: str
    reason: Optional[str]
    status: str
    created_at: float
    resolved_at: Optional[float]
    resolved_by: Optional[int]
    resolution: Optional[str]
    resolution_reason: Optional[str]


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


class TicketRecord(TypedDict, total=False):
    """Type for ticket records."""
    id: int
    ticket_id: str
    user_id: int
    guild_id: int
    thread_id: int
    category: str
    subject: str
    status: str
    priority: str
    claimed_by: Optional[int]
    assigned_to: Optional[int]
    created_at: float
    closed_at: Optional[float]
    closed_by: Optional[int]
    close_reason: Optional[str]


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
                timeout=30.0,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
            self._conn.execute("PRAGMA busy_timeout=5000")  # 5s busy timeout
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
        # DESIGN: Logs messages for context and history
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
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_guild_time ON messages(user_id, guild_id, timestamp DESC)"
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
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mute_history_user_time ON mute_history(user_id, guild_id, timestamp DESC)"
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
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN last_mute_duration TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN last_mute_moderator_id INTEGER")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN last_ban_moderator_id INTEGER")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN last_ban_reason TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN warn_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE case_logs ADD COLUMN last_warn_at REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # -----------------------------------------------------------------
        # Cases Table (NEW - Per-Action Cases)
        # DESIGN: One case per moderation action (mute/ban/warn)
        # Each action gets its own thread and case_id
        # Unmute/unban resolves the corresponding case
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                duration_seconds INTEGER,
                evidence TEXT,
                created_at REAL NOT NULL,
                resolved_at REAL,
                resolved_by INTEGER,
                resolved_reason TEXT
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_user ON cases(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status, action_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_thread ON cases(thread_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_case_id ON cases(case_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_guild_status ON cases(guild_id, status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_created ON cases(created_at DESC)"
        )

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

        # Migration: Add action tracking columns if they don't exist
        try:
            cursor.execute("ALTER TABLE mod_tracker ADD COLUMN action_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE mod_tracker ADD COLUMN last_action_at REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # -----------------------------------------------------------------
        # Mod Hourly Activity Table
        # DESIGN: Tracks mod activity by hour for peak hours analysis
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mod_hourly_activity (
                mod_id INTEGER NOT NULL,
                hour INTEGER NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (mod_id, hour)
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
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nickname_user_guild_time ON nickname_history(user_id, guild_id, changed_at DESC)"
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

        # Migration: Add join_message_id column for editing join embeds on leave
        try:
            cursor.execute("ALTER TABLE member_activity ADD COLUMN join_message_id INTEGER")
        except sqlite3.OperationalError:
            pass  # Column already exists

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

        # -----------------------------------------------------------------
        # Mod Notes Table
        # DESIGN: Stores moderator notes/comments about users
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mod_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mod_notes_user ON mod_notes(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mod_notes_time ON mod_notes(created_at)"
        )
        # Add case_id column if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE mod_notes ADD COLUMN case_id TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # -----------------------------------------------------------------
        # Ban History Table
        # DESIGN: Tracks all ban/unban actions for history display
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ban_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ban_history_user ON ban_history(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ban_history_time ON ban_history(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ban_history_user_time ON ban_history(user_id, guild_id, timestamp DESC)"
        )

        # -----------------------------------------------------------------
        # Username History Table
        # DESIGN: Tracks username/nickname changes for user identification
        # Keeps rolling window of last 10 changes per user
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS username_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                display_name TEXT,
                guild_id INTEGER,
                changed_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_username_history_user ON username_history(user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_username_history_time ON username_history(changed_at)"
        )

        # -----------------------------------------------------------------
        # Warnings Table
        # DESIGN: Tracks warnings issued to users by moderators
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                evidence TEXT,
                created_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_warnings_time ON warnings(created_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_warnings_user_time ON warnings(user_id, guild_id, created_at DESC)"
        )

        # -----------------------------------------------------------------
        # Voice Activity Table
        # DESIGN: Tracks voice channel joins/leaves for verification
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voice_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_activity_user ON voice_activity(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_activity_time ON voice_activity(timestamp)"
        )

        # -----------------------------------------------------------------
        # LOCKDOWN STATE TABLE
        # DESIGN: Tracks server lockdown status for raid protection
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lockdown_state (
                guild_id INTEGER PRIMARY KEY,
                locked_at REAL NOT NULL,
                locked_by INTEGER NOT NULL,
                reason TEXT,
                channel_count INTEGER DEFAULT 0
            )
        """)

        # -----------------------------------------------------------------
        # LOCKDOWN PERMISSIONS TABLE (Legacy - per-channel)
        # DESIGN: Stores original channel permissions before lockdown
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lockdown_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                channel_type TEXT NOT NULL,
                original_send_messages INTEGER,
                original_connect INTEGER,
                UNIQUE(guild_id, channel_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_lockdown_perms_guild ON lockdown_permissions(guild_id)"
        )

        # -----------------------------------------------------------------
        # LOCKDOWN ROLE PERMISSIONS TABLE
        # DESIGN: Stores original @everyone role permissions for instant lockdown
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lockdown_role_permissions (
                guild_id INTEGER PRIMARY KEY,
                send_messages INTEGER,
                connect INTEGER,
                add_reactions INTEGER,
                create_public_threads INTEGER,
                create_private_threads INTEGER,
                send_messages_in_threads INTEGER
            )
        """)

        # -----------------------------------------------------------------
        # SPAM VIOLATIONS TABLE
        # DESIGN: Persists spam violations across bot restarts
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spam_violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                violation_count INTEGER DEFAULT 1,
                last_violation_at REAL NOT NULL,
                last_spam_type TEXT,
                UNIQUE(user_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_spam_violations_user ON spam_violations(user_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # SNIPE CACHE TABLE
        # DESIGN: Persists deleted messages for /snipe command
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snipe_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                author_display TEXT NOT NULL,
                author_avatar TEXT,
                content TEXT,
                attachment_names TEXT,
                attachment_urls TEXT,
                attachment_data TEXT,
                sticker_urls TEXT,
                deleted_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_snipe_channel ON snipe_cache(channel_id, deleted_at DESC)"
        )
        # Migration: Add columns if missing
        for column, col_type in [
            ("attachment_urls", "TEXT"),
            ("sticker_urls", "TEXT"),
            ("message_id", "INTEGER"),
            ("attachment_data", "TEXT"),  # Base64-encoded file bytes
        ]:
            try:
                cursor.execute(f"ALTER TABLE snipe_cache ADD COLUMN {column} {col_type}")
            except Exception:
                pass  # Column already exists

        # -----------------------------------------------------------------
        # FORBID HISTORY TABLE
        # DESIGN: Tracks user restrictions (forbid reactions, attachments, etc.)
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forbid_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                restriction_type TEXT NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                created_at REAL NOT NULL,
                expires_at REAL,
                removed_at REAL,
                removed_by INTEGER,
                case_id TEXT,
                UNIQUE(user_id, guild_id, restriction_type)
            )
        """)
        # Add expires_at column if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE forbid_history ADD COLUMN expires_at REAL")
        except Exception:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE forbid_history ADD COLUMN case_id TEXT")
        except Exception:
            pass  # Column already exists
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_forbid_user ON forbid_history(user_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # APPEALS TABLE
        # DESIGN: Tracks appeal requests for bans and long mutes
        # Links to original case via case_id
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appeal_id TEXT UNIQUE NOT NULL,
                case_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL,
                resolved_at REAL,
                resolved_by INTEGER,
                resolution TEXT,
                resolution_reason TEXT
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_appeals_case ON appeals(case_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_appeals_user ON appeals(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_appeals_status ON appeals(status)"
        )

        # -----------------------------------------------------------------
        # Linked Messages Table
        # DESIGN: Links messages to members for auto-deletion on leave
        # Used for alliance channel posts that should be removed when member leaves
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS linked_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                linked_by INTEGER NOT NULL,
                linked_at REAL NOT NULL,
                UNIQUE(message_id, channel_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_linked_messages_member ON linked_messages(member_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # TICKETS TABLE
        # DESIGN: Tracks support tickets via forum threads
        # Sequential IDs like T001, T002, etc.
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                priority TEXT DEFAULT 'normal',
                claimed_by INTEGER,
                assigned_to INTEGER,
                created_at REAL NOT NULL,
                last_activity_at REAL,
                warned_at REAL,
                closed_at REAL,
                closed_by INTEGER,
                close_reason TEXT
            )
        """)
        # Migration: Add last_activity_at, warned_at, and claimed_at columns if they don't exist
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN last_activity_at REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN warned_at REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN claimed_at REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN transcript_html TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE tickets ADD COLUMN control_panel_message_id INTEGER")
        except sqlite3.OperationalError:
            pass  # Column already exists
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_claimed ON tickets(claimed_by)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_thread ON tickets(thread_id)"
        )

        # -----------------------------------------------------------------
        # MODMAIL TABLE
        # DESIGN: Tracks modmail threads for banned users
        # One thread per banned user
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS modmail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                status TEXT DEFAULT 'open',
                created_at REAL NOT NULL,
                closed_at REAL,
                closed_by INTEGER,
                UNIQUE(user_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_modmail_user ON modmail(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_modmail_thread ON modmail(thread_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_modmail_status ON modmail(status)"
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
            Checks both legacy case_logs and new cases tables for uniqueness.
            With 36^4 = 1,679,616 possible combinations, collisions are rare.

        Returns:
            Unique 4-character case ID (e.g., "A7X2", "K3M9").
        """
        chars = string.ascii_uppercase + string.digits  # A-Z, 0-9

        while True:
            # Generate random 4-character code
            case_id = ''.join(secrets.choice(chars) for _ in range(4))

            # Check if it already exists in legacy table
            row = self.fetchone(
                "SELECT 1 FROM case_logs WHERE case_id = ?",
                (case_id,)
            )
            if row:
                continue

            # Check if it exists in new cases table
            row = self.fetchone(
                "SELECT 1 FROM cases WHERE case_id = ?",
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
        duration: Optional[str] = None,
        moderator_id: Optional[int] = None,
    ) -> None:
        """
        Create a new case log for a user.

        Args:
            user_id: Discord user ID.
            case_id: Unique 4-character alphanumeric case ID.
            thread_id: Forum thread ID for this case.
            duration: Optional duration string of the first mute.
            moderator_id: Optional moderator ID who issued the first mute.
        """
        now = time.time()
        self.execute(
            """INSERT INTO case_logs
               (user_id, case_id, thread_id, mute_count, created_at, last_mute_at,
                last_mute_duration, last_mute_moderator_id)
               VALUES (?, ?, ?, 1, ?, ?, ?, ?)""",
            (user_id, case_id, thread_id, now, now, duration, moderator_id)
        )

        logger.tree("Case Log Created", [
            ("User ID", str(user_id)),
            ("Case ID", case_id),
            ("Thread ID", str(thread_id)),
        ], emoji="📋")

    def increment_mute_count(
        self,
        user_id: int,
        duration: Optional[str] = None,
        moderator_id: Optional[int] = None,
    ) -> int:
        """
        Increment mute count for a user's case.

        Args:
            user_id: Discord user ID.
            duration: Optional duration string (e.g., "1h", "1d").
            moderator_id: Optional moderator ID who issued the mute.

        Returns:
            New mute count.
        """
        now = time.time()
        self.execute(
            """UPDATE case_logs
               SET mute_count = mute_count + 1,
                   last_mute_at = ?,
                   last_mute_duration = ?,
                   last_mute_moderator_id = ?
               WHERE user_id = ?""",
            (now, duration, moderator_id, user_id)
        )

        row = self.fetchone(
            "SELECT mute_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        return row["mute_count"] if row else 1

    def get_last_mute_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get last mute info for a user's case.

        Args:
            user_id: Discord user ID.

        Returns:
            Dict with last_mute_at, last_mute_duration, last_mute_moderator_id.
        """
        row = self.fetchone(
            """SELECT last_mute_at, last_mute_duration, last_mute_moderator_id
               FROM case_logs WHERE user_id = ?""",
            (user_id,)
        )
        if row:
            return {
                "last_mute_at": row["last_mute_at"],
                "last_mute_duration": row["last_mute_duration"],
                "last_mute_moderator_id": row["last_mute_moderator_id"],
            }
        return None

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

    def increment_ban_count(
        self,
        user_id: int,
        moderator_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> int:
        """
        Increment ban count for a user's case.

        Args:
            user_id: Discord user ID.
            moderator_id: Optional moderator ID who issued the ban.
            reason: Optional reason for the ban.

        Returns:
            New ban count.
        """
        now = time.time()
        self.execute(
            """UPDATE case_logs
               SET ban_count = COALESCE(ban_count, 0) + 1,
                   last_ban_at = ?,
                   last_ban_moderator_id = ?,
                   last_ban_reason = ?
               WHERE user_id = ?""",
            (now, moderator_id, reason, user_id)
        )

        row = self.fetchone(
            "SELECT ban_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        return row["ban_count"] if row and row["ban_count"] else 1

    def get_last_ban_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get last ban info for a user's case.

        Args:
            user_id: Discord user ID.

        Returns:
            Dict with last_ban_at, last_ban_moderator_id, last_ban_reason.
        """
        row = self.fetchone(
            """SELECT last_ban_at, last_ban_moderator_id, last_ban_reason
               FROM case_logs WHERE user_id = ?""",
            (user_id,)
        )
        if row:
            return {
                "last_ban_at": row["last_ban_at"],
                "last_ban_moderator_id": row["last_ban_moderator_id"],
                "last_ban_reason": row["last_ban_reason"],
            }
        return None

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

    # =========================================================================
    # Warning Operations
    # =========================================================================

    # Warnings older than this many days don't count toward active count
    WARNING_DECAY_DAYS = 30

    def add_warning(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> int:
        """
        Add a warning to the database.

        Args:
            user_id: Discord user ID being warned.
            guild_id: Guild where warning was issued.
            moderator_id: Moderator who issued warning.
            reason: Optional reason for warning.
            evidence: Optional evidence URL/text.

        Returns:
            Row ID of the warning record.
        """
        now = time.time()

        cursor = self.execute(
            """INSERT INTO warnings
               (user_id, guild_id, moderator_id, reason, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, moderator_id, reason, evidence, now)
        )

        logger.tree("Warning Added", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
            ("Reason", (reason or "None")[:50]),
        ], emoji="⚠️")

        return cursor.lastrowid

    def increment_warn_count(
        self,
        user_id: int,
        moderator_id: Optional[int] = None,
    ) -> int:
        """
        Increment warn count for a user's case.

        Args:
            user_id: Discord user ID.
            moderator_id: Optional moderator ID who issued the warning.

        Returns:
            New warn count.
        """
        now = time.time()
        self.execute(
            """UPDATE case_logs
               SET warn_count = COALESCE(warn_count, 0) + 1,
                   last_warn_at = ?
               WHERE user_id = ?""",
            (now, user_id)
        )

        row = self.fetchone(
            "SELECT warn_count FROM case_logs WHERE user_id = ?",
            (user_id,)
        )
        return row["warn_count"] if row and row["warn_count"] else 1

    def get_user_warn_count(self, user_id: int, guild_id: int) -> int:
        """
        Get total number of warnings for a user in a guild (all time).

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Total warning count.
        """
        row = self.fetchone(
            "SELECT COUNT(*) as count FROM warnings WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["count"] if row else 0

    def get_active_warn_count(self, user_id: int, guild_id: int) -> int:
        """
        Get number of active (non-expired) warnings for a user.

        Warnings older than WARNING_DECAY_DAYS are considered expired
        and don't count toward the active total.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Active warning count.
        """
        decay_cutoff = time.time() - (self.WARNING_DECAY_DAYS * 86400)
        row = self.fetchone(
            """SELECT COUNT(*) as count FROM warnings
               WHERE user_id = ? AND guild_id = ? AND created_at >= ?""",
            (user_id, guild_id, decay_cutoff)
        )
        return row["count"] if row else 0

    def get_warn_counts(self, user_id: int, guild_id: int) -> tuple:
        """
        Get both active and total warning counts for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Tuple of (active_count, total_count).
        """
        total = self.get_user_warn_count(user_id, guild_id)
        active = self.get_active_warn_count(user_id, guild_id)
        return (active, total)

    def get_user_warnings(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Get all warnings for a user in a guild.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum number of warnings to return.

        Returns:
            List of warning records.
        """
        rows = self.fetchall(
            """SELECT id, user_id, guild_id, moderator_id, reason, evidence, created_at
               FROM warnings
               WHERE user_id = ? AND guild_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

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
    # Per-Action Case Operations (NEW)
    # =========================================================================

    def create_case(
        self,
        case_id: str,
        user_id: int,
        guild_id: int,
        thread_id: int,
        action_type: str,
        moderator_id: int,
        reason: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        evidence: Optional[str] = None,
    ) -> str:
        """
        Create a new per-action case.

        Args:
            case_id: Unique 4-char case ID.
            user_id: Target user ID.
            guild_id: Guild ID.
            thread_id: Forum thread ID for this case.
            action_type: 'mute', 'ban', or 'warn'.
            moderator_id: Moderator who created the case.
            reason: Optional reason for the action.
            duration_seconds: Optional duration (for mutes).
            evidence: Optional evidence URL/text.

        Returns:
            The case_id.
        """
        now = time.time()
        self.execute(
            """INSERT INTO cases
               (case_id, user_id, guild_id, thread_id, action_type, status,
                moderator_id, reason, duration_seconds, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)""",
            (case_id, user_id, guild_id, thread_id, action_type,
             moderator_id, reason, duration_seconds, evidence, now)
        )
        return case_id

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a case by its ID.

        Args:
            case_id: The 4-char case ID.

        Returns:
            Case dict or None if not found.
        """
        row = self.fetchone(
            "SELECT * FROM cases WHERE case_id = ?",
            (case_id,)
        )
        return dict(row) if row else None

    def update_case_reason(self, case_id: str, new_reason: Optional[str], edited_by: int) -> bool:
        """
        Update the reason for a case.

        Args:
            case_id: The 4-char case ID.
            new_reason: The new reason text (or None to clear).
            edited_by: User ID of who edited the case.

        Returns:
            True if updated successfully, False otherwise.
        """
        try:
            self.execute(
                """
                UPDATE cases
                SET reason = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (new_reason, time.time(), case_id)
            )
            return True
        except Exception:
            return False

    def get_case_by_thread(self, thread_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a case by its thread ID.

        Args:
            thread_id: The forum thread ID.

        Returns:
            Case dict or None if not found.
        """
        row = self.fetchone(
            "SELECT * FROM cases WHERE thread_id = ?",
            (thread_id,)
        )
        return dict(row) if row else None

    def get_active_mute_case(
        self,
        user_id: int,
        guild_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent open mute case for a user.

        Used when unmuting to find the case thread to log to.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.

        Returns:
            Active mute case dict or None.
        """
        row = self.fetchone(
            """SELECT * FROM cases
               WHERE user_id = ? AND guild_id = ?
               AND action_type = 'mute' AND status = 'open'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    def get_active_ban_case(
        self,
        user_id: int,
        guild_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent open ban case for a user.

        Used when unbanning to find the case thread to log to.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.

        Returns:
            Active ban case dict or None.
        """
        row = self.fetchone(
            """SELECT * FROM cases
               WHERE user_id = ? AND guild_id = ?
               AND action_type = 'ban' AND status = 'open'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    def resolve_case(
        self,
        case_id: str,
        resolved_by: int,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Mark a case as resolved (for unmute/unban).

        Args:
            case_id: The case to resolve.
            resolved_by: User ID who resolved it.
            reason: Optional reason for resolution.

        Returns:
            True if case was resolved, False if not found or already resolved.
        """
        now = time.time()
        cursor = self.execute(
            """UPDATE cases
               SET status = 'resolved', resolved_at = ?, resolved_by = ?, resolved_reason = ?
               WHERE case_id = ? AND status = 'open'""",
            (now, resolved_by, reason, case_id)
        )
        return cursor.rowcount > 0

    def get_user_cases(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 25,
        include_resolved: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get all cases for a user, sorted by most recent.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.
            limit: Maximum number of cases to return.
            include_resolved: Whether to include resolved cases.

        Returns:
            List of case dicts.
        """
        if include_resolved:
            query = """SELECT * FROM cases
                       WHERE user_id = ? AND guild_id = ?
                       ORDER BY created_at DESC LIMIT ?"""
            rows = self.fetchall(query, (user_id, guild_id, limit))
        else:
            query = """SELECT * FROM cases
                       WHERE user_id = ? AND guild_id = ? AND status = 'open'
                       ORDER BY created_at DESC LIMIT ?"""
            rows = self.fetchall(query, (user_id, guild_id, limit))
        return [dict(row) for row in rows]

    def get_user_case_counts(self, user_id: int, guild_id: int) -> Dict[str, int]:
        """
        Get case counts by action type for a user.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.

        Returns:
            Dict with mute_count, ban_count, warn_count.
        """
        row = self.fetchone(
            """SELECT
                SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mute_count,
                SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as ban_count,
                SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warn_count
               FROM cases WHERE user_id = ? AND guild_id = ?""",
            (user_id, guild_id)
        )
        return {
            "mute_count": row["mute_count"] or 0 if row else 0,
            "ban_count": row["ban_count"] or 0 if row else 0,
            "warn_count": row["warn_count"] or 0 if row else 0,
        }

    def get_old_cases(self, cutoff_timestamp: float) -> List[Dict[str, Any]]:
        """
        Get cases older than the cutoff timestamp that aren't archived.

        Args:
            cutoff_timestamp: Unix timestamp cutoff (cases created before this).

        Returns:
            List of case dicts.
        """
        rows = self.fetchall(
            """SELECT * FROM cases
               WHERE created_at < ? AND status != 'archived'
               ORDER BY created_at ASC""",
            (cutoff_timestamp,)
        )
        return [dict(row) for row in rows]

    def archive_case(self, case_id: str) -> bool:
        """
        Mark a case as archived (thread was deleted).

        Args:
            case_id: The case ID to archive.

        Returns:
            True if case was archived, False if not found.
        """
        cursor = self.execute(
            "UPDATE cases SET status = 'archived' WHERE case_id = ?",
            (case_id,)
        )
        return cursor.rowcount > 0

    def get_most_recent_resolved_case(
        self,
        user_id: int,
        guild_id: int,
        action_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recently resolved case for a user.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.
            action_type: Type of action ('mute', 'ban', 'warn').

        Returns:
            Case dict with resolved_at, resolved_by, etc. or None.
        """
        row = self.fetchone(
            """SELECT * FROM cases
               WHERE user_id = ? AND guild_id = ? AND action_type = ?
               AND status = 'resolved'
               ORDER BY resolved_at DESC LIMIT 1""",
            (user_id, guild_id, action_type)
        )
        return dict(row) if row else None

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

    def increment_mod_action_count(self, mod_id: int) -> int:
        """
        Increment the action count for a mod and update last action time.

        Args:
            mod_id: Discord user ID.

        Returns:
            New action count.
        """
        now = time.time()
        self.execute(
            """UPDATE mod_tracker
               SET action_count = COALESCE(action_count, 0) + 1,
                   last_action_at = ?
               WHERE mod_id = ?""",
            (now, mod_id)
        )
        row = self.fetchone(
            "SELECT action_count FROM mod_tracker WHERE mod_id = ?",
            (mod_id,)
        )
        return row["action_count"] if row else 0

    def get_mod_action_count(self, mod_id: int) -> int:
        """
        Get the action count for a mod.

        Args:
            mod_id: Discord user ID.

        Returns:
            Action count (0 if not found).
        """
        row = self.fetchone(
            "SELECT action_count FROM mod_tracker WHERE mod_id = ?",
            (mod_id,)
        )
        return row["action_count"] if row and row["action_count"] else 0

    def increment_hourly_activity(self, mod_id: int, hour: int) -> None:
        """
        Increment the hourly activity count for a mod.

        Args:
            mod_id: Discord user ID.
            hour: Hour of day (0-23).
        """
        self.execute(
            """INSERT INTO mod_hourly_activity (mod_id, hour, count)
               VALUES (?, ?, 1)
               ON CONFLICT(mod_id, hour) DO UPDATE SET count = count + 1""",
            (mod_id, hour)
        )

    def get_peak_hours(self, mod_id: int, top_n: int = 3) -> list:
        """
        Get the peak activity hours for a mod.

        Args:
            mod_id: Discord user ID.
            top_n: Number of top hours to return.

        Returns:
            List of tuples (hour, count) sorted by count descending.
        """
        rows = self.fetchall(
            """SELECT hour, count FROM mod_hourly_activity
               WHERE mod_id = ? AND count > 0
               ORDER BY count DESC
               LIMIT ?""",
            (mod_id, top_n)
        )
        return [(row["hour"], row["count"]) for row in rows]

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

    def record_member_join(self, user_id: int, guild_id: int, join_message_id: Optional[int] = None) -> int:
        """
        Record a member join and return their join count.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            join_message_id: Optional message ID of the join log embed.

        Returns:
            The member's total join count (including this one).
        """
        now = time.time()
        # Insert or update the member activity record
        self.execute(
            """INSERT INTO member_activity (user_id, guild_id, join_count, first_joined_at, last_joined_at, join_message_id)
               VALUES (?, ?, 1, ?, ?, ?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET
                   join_count = join_count + 1,
                   last_joined_at = ?,
                   join_message_id = ?""",
            (user_id, guild_id, now, now, join_message_id, now, join_message_id)
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

    def get_join_message_id(self, user_id: int, guild_id: int) -> Optional[int]:
        """
        Get the join message ID for a member (without clearing).

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            The join message ID if it exists, or None.
        """
        row = self.fetchone(
            "SELECT join_message_id FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["join_message_id"] if row and row["join_message_id"] else None

    def pop_join_message_id(self, user_id: int, guild_id: int) -> Optional[int]:
        """
        Get and clear the join message ID for a member.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            The join message ID if it exists, or None.
        """
        row = self.fetchone(
            "SELECT join_message_id FROM member_activity WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        if row and row["join_message_id"]:
            # Clear the message ID
            self.execute(
                "UPDATE member_activity SET join_message_id = NULL WHERE user_id = ? AND guild_id = ?",
                (user_id, guild_id)
            )
            return row["join_message_id"]
        return None

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
        cursor = self.execute(
            """
            INSERT INTO pending_reasons
            (thread_id, warning_message_id, embed_message_id, moderator_id, target_user_id, action_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (thread_id, warning_message_id, embed_message_id, moderator_id, target_user_id, action_type, time.time())
        )
        return cursor.lastrowid or 0

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
        cursor = self.execute(
            "DELETE FROM pending_reasons WHERE owner_notified = 1 AND created_at < ?",
            (cutoff,)
        )
        return cursor.rowcount

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
        rows = self.fetchall(
            "SELECT * FROM alt_links WHERE banned_user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        results = []
        for row in rows:
            record = dict(row)
            record['signals'] = _safe_json_loads(record['signals'], default=[])
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
        rows = self.fetchall(
            "SELECT * FROM alt_links WHERE potential_alt_id = ? AND guild_id = ?",
            (alt_id, guild_id)
        )
        results = []
        for row in rows:
            record = dict(row)
            record['signals'] = _safe_json_loads(record['signals'], default=[])
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


    # =========================================================================
    # Mod Notes Operations
    # =========================================================================

    def save_mod_note(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        note: str,
        case_id: Optional[str] = None,
    ) -> int:
        """
        Save a moderator note about a user.

        Args:
            user_id: Discord user ID the note is about.
            guild_id: Guild ID.
            moderator_id: Moderator who created the note.
            note: The note text.
            case_id: Optional case ID to link this note to.

        Returns:
            The row ID of the inserted note.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO mod_notes
               (user_id, guild_id, moderator_id, note, created_at, case_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, moderator_id, note, now, case_id)
        )

        logger.tree("MOD NOTE SAVED", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
            ("Case ID", case_id or "N/A"),
            ("Note", (note[:40] + "...") if len(note) > 40 else note),
        ], emoji="📝")

        return cursor.lastrowid

    def get_mod_notes(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 20,
        case_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get moderator notes for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.
            case_id: Optional case ID to filter by.

        Returns:
            List of note records, newest first.
        """
        if case_id:
            rows = self.fetchall(
                """SELECT * FROM mod_notes
                   WHERE user_id = ? AND guild_id = ? AND case_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (user_id, guild_id, case_id, limit)
            )
        else:
            rows = self.fetchall(
                """SELECT * FROM mod_notes
                   WHERE user_id = ? AND guild_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (user_id, guild_id, limit)
            )
        return [dict(row) for row in rows]

    def get_note_count(self, user_id: int, guild_id: int) -> int:
        """
        Get total note count for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Total note count.
        """
        row = self.fetchone(
            "SELECT COUNT(*) as count FROM mod_notes WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["count"] if row else 0

    # =========================================================================
    # Ban History Operations
    # =========================================================================

    def add_ban(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
    ) -> int:
        """
        Add a ban record to history.

        Args:
            user_id: Discord user ID being banned.
            guild_id: Guild ID.
            moderator_id: Moderator who issued the ban.
            reason: Optional reason for ban.

        Returns:
            Row ID of the ban record.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO ban_history
               (user_id, guild_id, moderator_id, action, reason, timestamp)
               VALUES (?, ?, ?, 'ban', ?, ?)""",
            (user_id, guild_id, moderator_id, reason, now)
        )
        return cursor.lastrowid

    def add_unban(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
    ) -> int:
        """
        Add an unban record to history.

        Args:
            user_id: Discord user ID being unbanned.
            guild_id: Guild ID.
            moderator_id: Moderator who issued the unban.
            reason: Optional reason for unban.

        Returns:
            Row ID of the unban record.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO ban_history
               (user_id, guild_id, moderator_id, action, reason, timestamp)
               VALUES (?, ?, ?, 'unban', ?, ?)""",
            (user_id, guild_id, moderator_id, reason, now)
        )
        return cursor.lastrowid

    def get_ban_history(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get ban history for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.

        Returns:
            List of ban history records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM ban_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

    def get_repeat_ban_offenders(
        self,
        guild_id: int,
        min_bans: int = 2,
        days: int = 90,
    ) -> List[Dict[str, Any]]:
        """
        Get users with multiple bans in the specified time window.

        Args:
            guild_id: Guild ID.
            min_bans: Minimum number of bans to qualify.
            days: Look back this many days.

        Returns:
            List of {user_id, ban_count, last_ban} for repeat offenders.
        """
        cutoff = time.time() - (days * 86400)
        rows = self.fetchall(
            """SELECT user_id, COUNT(*) as ban_count, MAX(timestamp) as last_ban
               FROM ban_history
               WHERE guild_id = ? AND action = 'ban' AND timestamp > ?
               GROUP BY user_id
               HAVING ban_count >= ?
               ORDER BY ban_count DESC""",
            (guild_id, cutoff, min_bans)
        )
        return [dict(row) for row in rows] if rows else []

    def get_quick_unban_patterns(
        self,
        guild_id: int,
        max_hours: int = 24,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Find suspicious patterns where users were unbanned quickly after ban.

        Args:
            guild_id: Guild ID.
            max_hours: Unban within this many hours is suspicious.
            days: Look back this many days.

        Returns:
            List of {user_id, ban_time, unban_time, hours_between}.
        """
        cutoff = time.time() - (days * 86400)
        max_seconds = max_hours * 3600

        rows = self.fetchall(
            """SELECT
                b.user_id,
                b.timestamp as ban_time,
                u.timestamp as unban_time,
                (u.timestamp - b.timestamp) / 3600.0 as hours_between,
                b.moderator_id as ban_mod,
                u.moderator_id as unban_mod
               FROM ban_history b
               INNER JOIN ban_history u ON b.user_id = u.user_id
                   AND b.guild_id = u.guild_id
                   AND u.action = 'unban'
                   AND u.timestamp > b.timestamp
                   AND u.timestamp - b.timestamp < ?
               WHERE b.guild_id = ? AND b.action = 'ban' AND b.timestamp > ?
               ORDER BY hours_between ASC""",
            (max_seconds, guild_id, cutoff)
        )
        return [dict(row) for row in rows] if rows else []

    # =========================================================================
    # Voice Activity Pattern Detection
    # =========================================================================

    def detect_voice_channel_hopping(
        self,
        guild_id: int,
        window_minutes: int = 5,
        min_channels: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Detect users rapidly switching between voice channels.

        Args:
            guild_id: Guild ID.
            window_minutes: Time window in minutes.
            min_channels: Minimum unique channels to qualify as hopping.

        Returns:
            List of {user_id, channel_count, actions} for channel hoppers.
        """
        cutoff = time.time() - (window_minutes * 60)

        rows = self.fetchall(
            """SELECT user_id, COUNT(DISTINCT channel_id) as channel_count,
                      COUNT(*) as action_count
               FROM voice_activity
               WHERE guild_id = ? AND timestamp > ? AND action = 'join'
               GROUP BY user_id
               HAVING channel_count >= ?
               ORDER BY channel_count DESC""",
            (guild_id, cutoff, min_channels)
        )
        return [dict(row) for row in rows] if rows else []

    def detect_voice_following(
        self,
        target_user_id: int,
        guild_id: int,
        window_minutes: int = 30,
        min_follows: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Detect if someone is following a specific user between voice channels.

        Args:
            target_user_id: The user being potentially stalked.
            guild_id: Guild ID.
            window_minutes: Time window in minutes.
            min_follows: Minimum follows to qualify.

        Returns:
            List of {follower_id, follow_count, channels} for potential stalkers.
        """
        cutoff = time.time() - (window_minutes * 60)

        # Get target's channel history
        target_channels = self.fetchall(
            """SELECT channel_id, timestamp FROM voice_activity
               WHERE user_id = ? AND guild_id = ? AND action = 'join' AND timestamp > ?
               ORDER BY timestamp""",
            (target_user_id, guild_id, cutoff)
        )

        if not target_channels:
            return []

        # Check each other user's joins within 60s of target's joins
        followers = {}
        for tc in target_channels:
            channel_id = tc["channel_id"]
            target_time = tc["timestamp"]

            # Find users who joined same channel within 60 seconds after target
            rows = self.fetchall(
                """SELECT user_id FROM voice_activity
                   WHERE guild_id = ? AND channel_id = ? AND action = 'join'
                   AND user_id != ? AND timestamp > ? AND timestamp < ?""",
                (guild_id, channel_id, target_user_id, target_time, target_time + 60)
            )

            for row in rows:
                uid = row["user_id"]
                if uid not in followers:
                    followers[uid] = {"follower_id": uid, "follow_count": 0, "channels": []}
                followers[uid]["follow_count"] += 1
                followers[uid]["channels"].append(channel_id)

        # Filter by min_follows
        return [f for f in followers.values() if f["follow_count"] >= min_follows]

    # =========================================================================
    # Username Cross-Reference for Ban Evasion
    # =========================================================================

    def find_banned_user_matches(
        self,
        guild_id: int,
        similarity_threshold: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        Find current members with usernames similar to banned users.

        Args:
            guild_id: Guild ID.
            similarity_threshold: Minimum similarity score (0-1).

        Returns:
            List of {current_user_id, current_name, banned_user_id, banned_name, similarity}.
        """
        # Get all unique banned user IDs
        banned_rows = self.fetchall(
            """SELECT DISTINCT user_id FROM ban_history
               WHERE guild_id = ? AND action = 'ban'""",
            (guild_id,)
        )
        banned_ids = {row["user_id"] for row in banned_rows}

        if not banned_ids:
            return []

        # Get username history for banned users
        banned_names = {}
        for uid in banned_ids:
            rows = self.fetchall(
                """SELECT username, display_name FROM username_history
                   WHERE user_id = ? ORDER BY changed_at DESC LIMIT 5""",
                (uid,)
            )
            for row in rows:
                if row["username"]:
                    banned_names[row["username"].lower()] = uid
                if row["display_name"]:
                    banned_names[row["display_name"].lower()] = uid

        # Get recent username changes (potential evaders)
        recent_names = self.fetchall(
            """SELECT user_id, username, display_name FROM username_history
               WHERE guild_id = ? AND user_id NOT IN ({})
               AND changed_at > ?
               ORDER BY changed_at DESC""".format(",".join("?" * len(banned_ids))),
            (guild_id, *banned_ids, time.time() - 86400 * 7)  # Last 7 days
        )

        matches = []
        for row in recent_names:
            current_id = row["user_id"]
            for name_field in ["username", "display_name"]:
                current_name = row[name_field]
                if not current_name:
                    continue
                current_lower = current_name.lower()

                for banned_name, banned_id in banned_names.items():
                    similarity = self._calculate_name_similarity(current_lower, banned_name)
                    if similarity >= similarity_threshold:
                        matches.append({
                            "current_user_id": current_id,
                            "current_name": current_name,
                            "banned_user_id": banned_id,
                            "banned_name": banned_name,
                            "similarity": similarity,
                        })

        return matches

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two names (0-1)."""
        if name1 == name2:
            return 1.0

        # Exact substring match
        if name1 in name2 or name2 in name1:
            return 0.9

        # Character-based similarity (Jaccard)
        set1 = set(name1.replace(" ", ""))
        set2 = set(name2.replace(" ", ""))
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    # =========================================================================
    # Extend Mute Operation
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

        # Update the mute
        self.execute(
            "UPDATE active_mutes SET expires_at = ? WHERE id = ?",
            (new_expires, row["id"])
        )

        # Log to history
        self.execute(
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

    # =========================================================================
    # Combined History for Display
    # =========================================================================

    def get_combined_history(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 25,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Get combined mute, ban, and note history for a user.

        Returns a unified list sorted by timestamp, with type indicators.
        Uses single UNION ALL query for efficiency.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.
            offset: Number of records to skip (for pagination).

        Returns:
            List of history records with 'type' field indicating category.
        """
        # Single UNION ALL query - sorted and paginated in SQL
        rows = self.fetchall(
            """SELECT id, user_id, guild_id, moderator_id, action, reason,
                      duration_seconds, timestamp, 'mute' as type
               FROM mute_history
               WHERE user_id = ? AND guild_id = ?
               UNION ALL
               SELECT id, user_id, guild_id, moderator_id, action, reason,
                      NULL as duration_seconds, timestamp, 'ban' as type
               FROM ban_history
               WHERE user_id = ? AND guild_id = ?
               UNION ALL
               SELECT id, user_id, guild_id, moderator_id, 'warn' as action, reason,
                      NULL as duration_seconds, created_at as timestamp, 'warn' as type
               FROM warnings
               WHERE user_id = ? AND guild_id = ?
               ORDER BY timestamp DESC
               LIMIT ? OFFSET ?""",
            (user_id, guild_id, user_id, guild_id, user_id, guild_id, limit, offset)
        )

        combined = [dict(row) for row in rows]

        # Log history query
        logger.tree("HISTORY QUERIED", [
            ("User ID", str(user_id)),
            ("Total", str(len(combined))),
        ], emoji="📋")

        return combined

    def get_history_count(self, user_id: int, guild_id: int) -> int:
        """
        Get total count of history records (mutes + bans + warnings).
        Uses single query with subqueries for efficiency.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Total count.
        """
        row = self.fetchone(
            """SELECT
                (SELECT COUNT(*) FROM mute_history WHERE user_id = ? AND guild_id = ?) +
                (SELECT COUNT(*) FROM ban_history WHERE user_id = ? AND guild_id = ?) +
                (SELECT COUNT(*) FROM warnings WHERE user_id = ? AND guild_id = ?) as total""",
            (user_id, guild_id, user_id, guild_id, user_id, guild_id)
        )
        return row["total"] if row else 0

    # =========================================================================
    # Username History Operations
    # =========================================================================

    def save_username_change(
        self,
        user_id: int,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        guild_id: Optional[int] = None,
    ) -> int:
        """
        Save a username or nickname change to history.

        Automatically maintains a rolling window of 10 entries per user.

        Args:
            user_id: Discord user ID.
            username: Global username (if changed).
            display_name: Server nickname (if changed).
            guild_id: Guild ID for nickname changes (None for global).

        Returns:
            The row ID of the inserted record.
        """
        now = time.time()

        # Insert new record
        cursor = self.execute(
            """INSERT INTO username_history
               (user_id, username, display_name, guild_id, changed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, display_name, guild_id, now)
        )
        new_id = cursor.lastrowid

        # Clean up old records - keep only last 10 per user
        self.execute(
            """DELETE FROM username_history
               WHERE user_id = ? AND id NOT IN (
                   SELECT id FROM username_history
                   WHERE user_id = ?
                   ORDER BY changed_at DESC
                   LIMIT 10
               )""",
            (user_id, user_id)
        )

        return new_id

    def get_username_history(
        self,
        user_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get username history for a user.

        Args:
            user_id: Discord user ID.
            limit: Maximum records to return.

        Returns:
            List of username history records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM username_history
               WHERE user_id = ?
               ORDER BY changed_at DESC
               LIMIT ?""",
            (user_id, limit)
        )
        return [dict(row) for row in rows]

    def get_previous_names(
        self,
        user_id: int,
        limit: int = 5,
    ) -> List[str]:
        """
        Get a simple list of previous usernames/nicknames for display.

        Args:
            user_id: Discord user ID.
            limit: Maximum names to return.

        Returns:
            List of unique previous names, newest first.
        """
        rows = self.fetchall(
            """SELECT username, display_name FROM username_history
               WHERE user_id = ?
               ORDER BY changed_at DESC
               LIMIT ?""",
            (user_id, limit * 2)  # Fetch more to account for duplicates
        )

        # Collect unique names
        seen = set()
        names = []
        for row in rows:
            # Prefer username, fallback to display_name
            name = row["username"] or row["display_name"]
            if name and name not in seen:
                seen.add(name)
                names.append(name)
                if len(names) >= limit:
                    break

        return names

    def has_username_history(self, user_id: int) -> bool:
        """
        Check if a user has any username history.

        Args:
            user_id: Discord user ID.

        Returns:
            True if history exists.
        """
        row = self.fetchone(
            "SELECT 1 FROM username_history WHERE user_id = ? LIMIT 1",
            (user_id,)
        )
        return row is not None

    # =========================================================================
    # Voice Activity Operations
    # =========================================================================

    def save_voice_activity(
        self,
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
        from datetime import datetime
        from src.core.config import NY_TZ

        self.execute(
            """INSERT INTO voice_activity
               (user_id, guild_id, channel_id, channel_name, action, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, channel_id, channel_name, action, datetime.now(NY_TZ).timestamp())
        )

    def get_recent_voice_activity(
        self,
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
        from datetime import datetime
        from src.core.config import NY_TZ

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

    def cleanup_old_voice_activity(self, max_age_seconds: int = 86400) -> int:
        """
        Clean up old voice activity records.

        Args:
            max_age_seconds: Delete records older than this (default 24h).

        Returns:
            Number of records deleted.
        """
        from datetime import datetime
        from src.core.config import NY_TZ

        cutoff = datetime.now(NY_TZ).timestamp() - max_age_seconds
        cursor = self.execute(
            "DELETE FROM voice_activity WHERE timestamp < ?",
            (cutoff,)
        )
        return cursor.rowcount if cursor else 0

    # =========================================================================
    # Lockdown Operations
    # =========================================================================

    def start_lockdown(
        self,
        guild_id: int,
        locked_by: int,
        reason: Optional[str] = None,
        channel_count: int = 0
    ) -> None:
        """
        Record a server lockdown.

        Args:
            guild_id: Guild being locked.
            locked_by: Moderator who initiated lockdown.
            reason: Reason for lockdown.
            channel_count: Number of channels locked.
        """
        self.execute(
            """INSERT OR REPLACE INTO lockdown_state
               (guild_id, locked_at, locked_by, reason, channel_count)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, time.time(), locked_by, reason, channel_count)
        )

    def end_lockdown(self, guild_id: int) -> None:
        """
        End a server lockdown and clear saved permissions.

        Args:
            guild_id: Guild to unlock.
        """
        self.execute("DELETE FROM lockdown_state WHERE guild_id = ?", (guild_id,))
        self.execute("DELETE FROM lockdown_permissions WHERE guild_id = ?", (guild_id,))

    def is_locked(self, guild_id: int) -> bool:
        """
        Check if a guild is currently locked.

        Args:
            guild_id: Guild to check.

        Returns:
            True if guild is locked.
        """
        row = self.fetchone(
            "SELECT 1 FROM lockdown_state WHERE guild_id = ?",
            (guild_id,)
        )
        return row is not None

    def get_lockdown_state(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """
        Get lockdown state for a guild.

        Args:
            guild_id: Guild to check.

        Returns:
            Lockdown info dict or None if not locked.
        """
        row = self.fetchone(
            "SELECT * FROM lockdown_state WHERE guild_id = ?",
            (guild_id,)
        )
        return dict(row) if row else None

    def save_channel_permission(
        self,
        guild_id: int,
        channel_id: int,
        channel_type: str,
        send_messages: Optional[bool],
        connect: Optional[bool]
    ) -> None:
        """
        Save original channel permission before lockdown.

        Args:
            guild_id: Guild ID.
            channel_id: Channel ID.
            channel_type: 'text' or 'voice'.
            send_messages: Original send_messages permission (None, True, False).
            connect: Original connect permission (None, True, False).
        """
        # Convert bool/None to int for storage (None=NULL, True=1, False=0)
        send_int = None if send_messages is None else (1 if send_messages else 0)
        connect_int = None if connect is None else (1 if connect else 0)

        self.execute(
            """INSERT OR REPLACE INTO lockdown_permissions
               (guild_id, channel_id, channel_type, original_send_messages, original_connect)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, channel_id, channel_type, send_int, connect_int)
        )

    def get_channel_permissions(self, guild_id: int) -> List[Dict[str, Any]]:
        """
        Get all saved channel permissions for a guild.

        Args:
            guild_id: Guild to get permissions for.

        Returns:
            List of permission records.
        """
        rows = self.fetchall(
            "SELECT * FROM lockdown_permissions WHERE guild_id = ?",
            (guild_id,)
        )
        result = []
        for row in rows:
            record = dict(row)
            # Convert stored ints back to bool/None
            send = record.get("original_send_messages")
            connect = record.get("original_connect")
            record["original_send_messages"] = None if send is None else bool(send)
            record["original_connect"] = None if connect is None else bool(connect)
            result.append(record)
        return result

    def clear_lockdown_permissions(self, guild_id: int) -> None:
        """
        Clear saved channel permissions for a guild.

        Args:
            guild_id: Guild to clear permissions for.
        """
        self.execute("DELETE FROM lockdown_permissions WHERE guild_id = ?", (guild_id,))
        self.execute("DELETE FROM lockdown_role_permissions WHERE guild_id = ?", (guild_id,))

    # =========================================================================
    # Role-Based Lockdown Operations
    # =========================================================================

    def save_lockdown_permissions(
        self,
        guild_id: int,
        send_messages: bool,
        connect: bool,
        add_reactions: bool,
        create_public_threads: bool,
        create_private_threads: bool,
        send_messages_in_threads: bool,
    ) -> None:
        """
        Save original @everyone role permissions before lockdown.

        Args:
            guild_id: Guild ID.
            send_messages: Original send_messages permission.
            connect: Original connect permission.
            add_reactions: Original add_reactions permission.
            create_public_threads: Original create_public_threads permission.
            create_private_threads: Original create_private_threads permission.
            send_messages_in_threads: Original send_messages_in_threads permission.
        """
        self.execute(
            """INSERT OR REPLACE INTO lockdown_role_permissions
               (guild_id, send_messages, connect, add_reactions,
                create_public_threads, create_private_threads, send_messages_in_threads)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                guild_id,
                1 if send_messages else 0,
                1 if connect else 0,
                1 if add_reactions else 0,
                1 if create_public_threads else 0,
                1 if create_private_threads else 0,
                1 if send_messages_in_threads else 0,
            )
        )

    def get_lockdown_permissions(self, guild_id: int) -> Optional[Dict[str, bool]]:
        """
        Get saved @everyone role permissions for a guild.

        Args:
            guild_id: Guild to get permissions for.

        Returns:
            Dict with permission booleans or None if not found.
        """
        row = self.fetchone(
            "SELECT * FROM lockdown_role_permissions WHERE guild_id = ?",
            (guild_id,)
        )
        if not row:
            return None
        return {
            "send_messages": bool(row["send_messages"]),
            "connect": bool(row["connect"]),
            "add_reactions": bool(row["add_reactions"]),
            "create_public_threads": bool(row["create_public_threads"]),
            "create_private_threads": bool(row["create_private_threads"]),
            "send_messages_in_threads": bool(row["send_messages_in_threads"]),
        }


    # =========================================================================
    # Spam Violations Operations
    # =========================================================================

    def get_spam_violations(self, user_id: int, guild_id: int) -> Dict[str, Any]:
        """
        Get spam violation record for a user.

        Args:
            user_id: User ID
            guild_id: Guild ID

        Returns:
            Dict with violation_count, last_violation_at, last_spam_type
            or defaults if no record exists
        """
        row = self.fetchone(
            "SELECT violation_count, last_violation_at, last_spam_type "
            "FROM spam_violations WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        if row:
            return {
                "violation_count": row["violation_count"],
                "last_violation_at": row["last_violation_at"],
                "last_spam_type": row["last_spam_type"],
            }
        return {
            "violation_count": 0,
            "last_violation_at": None,
            "last_spam_type": None,
        }

    def add_spam_violation(
        self,
        user_id: int,
        guild_id: int,
        spam_type: str,
    ) -> int:
        """
        Add or increment spam violation for a user.

        Args:
            user_id: User ID
            guild_id: Guild ID
            spam_type: Type of spam detected

        Returns:
            New violation count
        """
        now = time.time()
        existing = self.get_spam_violations(user_id, guild_id)

        if existing["violation_count"] > 0:
            new_count = existing["violation_count"] + 1
            self.execute(
                "UPDATE spam_violations SET violation_count = ?, "
                "last_violation_at = ?, last_spam_type = ? "
                "WHERE user_id = ? AND guild_id = ?",
                (new_count, now, spam_type, user_id, guild_id)
            )
        else:
            new_count = 1
            self.execute(
                "INSERT INTO spam_violations "
                "(user_id, guild_id, violation_count, last_violation_at, last_spam_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, guild_id, 1, now, spam_type)
            )

        return new_count

    def decay_spam_violations(self, decay_seconds: int = 300) -> int:
        """
        Decay violations for users who haven't violated in a while.

        Args:
            decay_seconds: Time since last violation to decay (default 5 min)

        Returns:
            Number of records affected
        """
        cutoff = time.time() - decay_seconds
        # Decrement by 1, delete if reaches 0
        self.execute(
            "UPDATE spam_violations SET violation_count = violation_count - 1 "
            "WHERE last_violation_at < ? AND violation_count > 0",
            (cutoff,)
        )
        # Clean up zero violations
        result = self.execute(
            "DELETE FROM spam_violations WHERE violation_count <= 0"
        )
        return result.rowcount if result else 0

    def reset_spam_violations(self, user_id: int, guild_id: int) -> None:
        """
        Reset spam violations for a user (e.g., after manual review).

        Args:
            user_id: User ID
            guild_id: Guild ID
        """
        self.execute(
            "DELETE FROM spam_violations WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )

    # =========================================================================
    # Forbid Operations
    # =========================================================================

    def add_forbid(
        self,
        user_id: int,
        guild_id: int,
        restriction_type: str,
        moderator_id: int,
        reason: Optional[str] = None,
        expires_at: Optional[float] = None,
        case_id: Optional[str] = None,
    ) -> bool:
        """
        Add a restriction to a user.

        Returns True if added, False if already exists.
        """
        now = time.time()
        try:
            self.execute(
                """INSERT OR REPLACE INTO forbid_history
                   (user_id, guild_id, restriction_type, moderator_id, reason, created_at, expires_at, removed_at, removed_by, case_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (user_id, guild_id, restriction_type, moderator_id, reason, now, expires_at, case_id)
            )
            return True
        except Exception:
            return False

    def get_expired_forbids(self) -> List[Dict[str, Any]]:
        """Get all forbids that have expired but not yet removed."""
        now = time.time()
        rows = self.fetchall(
            """SELECT id, user_id, guild_id, restriction_type, moderator_id, reason, created_at, expires_at
               FROM forbid_history
               WHERE expires_at IS NOT NULL AND expires_at <= ? AND removed_at IS NULL""",
            (now,)
        )
        return [dict(row) for row in rows]

    def update_forbid_case_id(
        self,
        user_id: int,
        guild_id: int,
        restriction_type: str,
        case_id: str,
    ) -> bool:
        """Update the case_id for a forbid entry."""
        cursor = self.execute(
            """UPDATE forbid_history SET case_id = ?
               WHERE user_id = ? AND guild_id = ? AND restriction_type = ? AND removed_at IS NULL""",
            (case_id, user_id, guild_id, restriction_type)
        )
        return cursor.rowcount > 0

    def remove_forbid(
        self,
        user_id: int,
        guild_id: int,
        restriction_type: str,
        removed_by: int,
    ) -> bool:
        """
        Remove a restriction from a user.

        Returns True if removed, False if didn't exist.
        """
        now = time.time()
        cursor = self.execute(
            """UPDATE forbid_history
               SET removed_at = ?, removed_by = ?
               WHERE user_id = ? AND guild_id = ? AND restriction_type = ? AND removed_at IS NULL""",
            (now, removed_by, user_id, guild_id, restriction_type)
        )
        return cursor.rowcount > 0

    def get_user_forbids(self, user_id: int, guild_id: int) -> List[Dict[str, Any]]:
        """
        Get all active restrictions for a user.

        Returns list of restriction records.
        """
        rows = self.fetchall(
            """SELECT restriction_type, moderator_id, reason, created_at
               FROM forbid_history
               WHERE user_id = ? AND guild_id = ? AND removed_at IS NULL
               ORDER BY created_at DESC""",
            (user_id, guild_id)
        )
        return [dict(row) for row in rows]

    def get_forbid_history(self, user_id: int, guild_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get full forbid history for a user (including removed).

        Returns list of all restriction records.
        """
        rows = self.fetchall(
            """SELECT restriction_type, moderator_id, reason, created_at, removed_at, removed_by
               FROM forbid_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

    def is_forbidden(self, user_id: int, guild_id: int, restriction_type: str) -> bool:
        """Check if user has a specific active restriction."""
        row = self.fetchone(
            """SELECT 1 FROM forbid_history
               WHERE user_id = ? AND guild_id = ? AND restriction_type = ? AND removed_at IS NULL""",
            (user_id, guild_id, restriction_type)
        )
        return row is not None

    # =========================================================================
    # Snipe Cache Operations
    # =========================================================================

    def save_snipe(
        self,
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
        import json

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

    def get_snipes(self, channel_id: int, limit: int = 10) -> List[Dict[str, Any]]:
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

    def clear_snipes(self, channel_id: int, user_id: Optional[int] = None) -> int:
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

    def cleanup_old_snipes(self, max_age_seconds: int = 600) -> int:
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
        return cursor.rowcount

    # =========================================================================
    # Appeal Operations
    # =========================================================================

    def get_next_appeal_id(self) -> str:
        """
        Generate next unique appeal ID (4 chars like AXXX).

        Returns:
            A unique 4-character appeal ID prefixed with 'A'.
        """
        # Prefix with 'A' for Appeal to distinguish from case IDs
        chars = string.ascii_uppercase + string.digits
        while True:
            appeal_id = 'A' + ''.join(secrets.choice(chars) for _ in range(3))
            existing = self.fetchone(
                "SELECT 1 FROM appeals WHERE appeal_id = ?",
                (appeal_id,)
            )
            if not existing:
                return appeal_id

    def create_appeal(
        self,
        appeal_id: str,
        case_id: str,
        user_id: int,
        guild_id: int,
        thread_id: int,
        action_type: str,
        reason: Optional[str] = None,
    ) -> None:
        """
        Create a new appeal.

        Args:
            appeal_id: Unique appeal ID.
            case_id: Original case ID being appealed.
            user_id: User submitting the appeal.
            guild_id: Guild ID.
            thread_id: Forum thread ID for this appeal.
            action_type: Type of action being appealed (ban/mute).
            reason: User's appeal reason.
        """
        self.execute(
            """INSERT INTO appeals (
                appeal_id, case_id, user_id, guild_id, thread_id,
                action_type, reason, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (appeal_id, case_id, user_id, guild_id, thread_id, action_type, reason, time.time())
        )

        logger.tree("Appeal Created", [
            ("Appeal ID", appeal_id),
            ("Case ID", case_id),
            ("User ID", str(user_id)),
            ("Type", action_type),
        ], emoji="📝")

    def get_appeal(self, appeal_id: str) -> Optional[AppealRecord]:
        """
        Get an appeal by its ID.

        Args:
            appeal_id: Appeal ID.

        Returns:
            Appeal record or None.
        """
        row = self.fetchone(
            "SELECT * FROM appeals WHERE appeal_id = ?",
            (appeal_id,)
        )
        return dict(row) if row else None

    def get_appeal_by_case(self, case_id: str) -> Optional[AppealRecord]:
        """
        Get appeal for a specific case.

        Args:
            case_id: Case ID.

        Returns:
            Appeal record or None.
        """
        row = self.fetchone(
            "SELECT * FROM appeals WHERE case_id = ?",
            (case_id,)
        )
        return dict(row) if row else None

    def get_pending_appeals(self, guild_id: int) -> List[AppealRecord]:
        """
        Get all pending appeals for a guild.

        Args:
            guild_id: Guild ID.

        Returns:
            List of pending appeal records.
        """
        rows = self.fetchall(
            """SELECT * FROM appeals
               WHERE guild_id = ? AND status = 'pending'
               ORDER BY created_at ASC""",
            (guild_id,)
        )
        return [dict(row) for row in rows]

    def get_user_appeals(self, user_id: int, guild_id: int) -> List[AppealRecord]:
        """
        Get all appeals for a user.

        Args:
            user_id: User ID.
            guild_id: Guild ID.

        Returns:
            List of appeal records.
        """
        rows = self.fetchall(
            """SELECT * FROM appeals
               WHERE user_id = ? AND guild_id = ?
               ORDER BY created_at DESC""",
            (user_id, guild_id)
        )
        return [dict(row) for row in rows]

    def resolve_appeal(
        self,
        appeal_id: str,
        resolution: str,
        resolved_by: int,
        resolution_reason: Optional[str] = None,
    ) -> bool:
        """
        Resolve an appeal (approve/deny/close).

        Args:
            appeal_id: Appeal ID to resolve.
            resolution: Resolution type (approved/denied/closed).
            resolved_by: Moderator ID who resolved.
            resolution_reason: Optional reason for resolution.

        Returns:
            True if appeal was found and updated.
        """
        cursor = self.execute(
            """UPDATE appeals
               SET status = 'resolved',
                   resolved_at = ?,
                   resolved_by = ?,
                   resolution = ?,
                   resolution_reason = ?
               WHERE appeal_id = ? AND status = 'pending'""",
            (time.time(), resolved_by, resolution, resolution_reason, appeal_id)
        )

        if cursor.rowcount > 0:
            logger.tree("Appeal Resolved", [
                ("Appeal ID", appeal_id),
                ("Resolution", resolution),
                ("Resolved By", str(resolved_by)),
            ], emoji="✅" if resolution == "approved" else "❌")
            return True
        return False

    def can_appeal_case(self, case_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if a case can be appealed.

        Args:
            case_id: Case ID to check.

        Returns:
            Tuple of (can_appeal, reason_if_not).
        """
        # Check if already appealed
        existing = self.fetchone(
            "SELECT status, resolution FROM appeals WHERE case_id = ?",
            (case_id,)
        )

        if existing:
            if existing["status"] == "pending":
                return (False, "Case already has a pending appeal")
            elif existing["resolution"] == "denied":
                return (False, "Appeal was already denied")
            elif existing["resolution"] == "approved":
                return (False, "Appeal was already approved")

        return (True, None)

    def get_last_appeal_time(self, case_id: str) -> Optional[float]:
        """
        Get the most recent appeal time for a case.

        Args:
            case_id: Case ID to check.

        Returns:
            Unix timestamp of last appeal or None.
        """
        row = self.fetchone(
            "SELECT created_at FROM appeals WHERE case_id = ? ORDER BY created_at DESC LIMIT 1",
            (case_id,)
        )
        return row["created_at"] if row else None

    def get_user_appeal_count_since(self, user_id: int, since_timestamp: float) -> int:
        """
        Count appeals from a user since a given time.

        Args:
            user_id: User ID to check.
            since_timestamp: Unix timestamp to count from.

        Returns:
            Number of appeals since the timestamp.
        """
        row = self.fetchone(
            "SELECT COUNT(*) as c FROM appeals WHERE user_id = ? AND created_at >= ?",
            (user_id, since_timestamp)
        )
        return row["c"] if row else 0

    def get_appealable_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """
        Get case info for appeal eligibility check.

        Args:
            case_id: Case ID.

        Returns:
            Case record or None.
        """
        row = self.fetchone(
            """SELECT case_id, user_id, guild_id, action_type,
                      duration_seconds, created_at, status, thread_id
               FROM cases
               WHERE case_id = ?""",
            (case_id,)
        )
        return dict(row) if row else None

    def get_appeal_stats(self, guild_id: int) -> Dict[str, int]:
        """
        Get appeal statistics for a guild.

        Args:
            guild_id: Guild ID.

        Returns:
            Dict with pending, approved, denied counts.
        """
        pending = self.fetchone(
            "SELECT COUNT(*) as c FROM appeals WHERE guild_id = ? AND status = 'pending'",
            (guild_id,)
        )
        approved = self.fetchone(
            "SELECT COUNT(*) as c FROM appeals WHERE guild_id = ? AND resolution = 'approved'",
            (guild_id,)
        )
        denied = self.fetchone(
            "SELECT COUNT(*) as c FROM appeals WHERE guild_id = ? AND resolution = 'denied'",
            (guild_id,)
        )

        return {
            "pending": pending["c"] if pending else 0,
            "approved": approved["c"] if approved else 0,
            "denied": denied["c"] if denied else 0,
        }

    # =========================================================================
    # Linked Messages Operations
    # =========================================================================

    def save_linked_message(
        self,
        message_id: int,
        channel_id: int,
        member_id: int,
        guild_id: int,
        linked_by: int,
    ) -> bool:
        """
        Link a message to a member for auto-deletion on leave.

        Args:
            message_id: Discord message ID.
            channel_id: Channel where message is.
            member_id: Member to link the message to.
            guild_id: Guild ID.
            linked_by: Moderator who created the link.

        Returns:
            True if saved, False if already linked.
        """
        try:
            self.execute(
                """INSERT INTO linked_messages
                   (message_id, channel_id, member_id, guild_id, linked_by, linked_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (message_id, channel_id, member_id, guild_id, linked_by, time.time())
            )
            return True
        except sqlite3.IntegrityError:
            return False  # Already linked

    def get_linked_messages_by_member(
        self,
        member_id: int,
        guild_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Get all messages linked to a member.

        Args:
            member_id: Member ID.
            guild_id: Guild ID.

        Returns:
            List of linked message records.
        """
        rows = self.fetchall(
            """SELECT message_id, channel_id, linked_by, linked_at
               FROM linked_messages
               WHERE member_id = ? AND guild_id = ?""",
            (member_id, guild_id)
        )
        return [dict(row) for row in rows]

    def delete_linked_message(self, message_id: int, channel_id: int) -> bool:
        """
        Remove a linked message record.

        Args:
            message_id: Discord message ID.
            channel_id: Channel ID.

        Returns:
            True if deleted, False if not found.
        """
        cursor = self.execute(
            "DELETE FROM linked_messages WHERE message_id = ? AND channel_id = ?",
            (message_id, channel_id)
        )
        return cursor.rowcount > 0

    def delete_linked_messages_by_member(self, member_id: int, guild_id: int) -> int:
        """
        Remove all linked messages for a member.

        Args:
            member_id: Member ID.
            guild_id: Guild ID.

        Returns:
            Number of records deleted.
        """
        cursor = self.execute(
            "DELETE FROM linked_messages WHERE member_id = ? AND guild_id = ?",
            (member_id, guild_id)
        )
        return cursor.rowcount

    def get_linked_message(self, message_id: int, channel_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a linked message record.

        Args:
            message_id: Discord message ID.
            channel_id: Channel ID.

        Returns:
            Linked message record or None.
        """
        row = self.fetchone(
            """SELECT message_id, channel_id, member_id, guild_id, linked_by, linked_at
               FROM linked_messages
               WHERE message_id = ? AND channel_id = ?""",
            (message_id, channel_id)
        )
        return dict(row) if row else None

    # =========================================================================
    # Ticket Operations
    # =========================================================================

    def generate_ticket_id(self) -> str:
        """
        Generate next sequential ticket ID (T001, T002, etc.).

        Returns:
            Next available ticket ID.
        """
        row = self.fetchone(
            "SELECT ticket_id FROM tickets ORDER BY id DESC LIMIT 1"
        )
        if row and row["ticket_id"]:
            # Extract number from T001 format
            try:
                num = int(row["ticket_id"][1:])
                return f"T{num + 1:03d}"
            except (ValueError, IndexError):
                pass
        return "T001"

    def create_ticket(
        self,
        ticket_id: str,
        user_id: int,
        guild_id: int,
        thread_id: int,
        category: str,
        subject: str,
    ) -> None:
        """
        Create a new support ticket.

        Args:
            ticket_id: Unique ticket ID (T001 format).
            user_id: User who opened the ticket.
            guild_id: Guild ID.
            thread_id: Forum thread ID for this ticket.
            category: Ticket category (support, partnership, etc.).
            subject: Ticket subject/title.
        """
        now = time.time()
        self.execute(
            """INSERT INTO tickets (
                ticket_id, user_id, guild_id, thread_id,
                category, subject, status, priority, created_at, last_activity_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'open', 'normal', ?, ?)""",
            (ticket_id, user_id, guild_id, thread_id, category, subject, now, now)
        )

        logger.tree("Ticket Created", [
            ("Ticket ID", ticket_id),
            ("Category", category),
            ("User ID", str(user_id)),
        ], emoji="🎫")

    def get_ticket(self, ticket_id: str) -> Optional[TicketRecord]:
        """
        Get a ticket by its ID.

        Args:
            ticket_id: Ticket ID.

        Returns:
            Ticket record or None.
        """
        row = self.fetchone(
            "SELECT * FROM tickets WHERE ticket_id = ?",
            (ticket_id,)
        )
        return dict(row) if row else None

    def get_ticket_by_thread(self, thread_id: int) -> Optional[TicketRecord]:
        """
        Get ticket by its forum thread ID.

        Args:
            thread_id: Discord thread ID.

        Returns:
            Ticket record or None.
        """
        row = self.fetchone(
            "SELECT * FROM tickets WHERE thread_id = ?",
            (thread_id,)
        )
        return dict(row) if row else None

    def get_user_tickets(self, user_id: int, guild_id: int) -> List[TicketRecord]:
        """
        Get all tickets for a user.

        Args:
            user_id: User ID.
            guild_id: Guild ID.

        Returns:
            List of ticket records.
        """
        rows = self.fetchall(
            """SELECT * FROM tickets
               WHERE user_id = ? AND guild_id = ?
               ORDER BY created_at DESC""",
            (user_id, guild_id)
        )
        return [dict(row) for row in rows]

    def get_open_tickets(self, guild_id: int) -> List[TicketRecord]:
        """
        Get all open tickets for a guild.

        Args:
            guild_id: Guild ID.

        Returns:
            List of open ticket records.
        """
        rows = self.fetchall(
            """SELECT * FROM tickets
               WHERE guild_id = ? AND status IN ('open', 'claimed')
               ORDER BY
                   CASE priority
                       WHEN 'urgent' THEN 1
                       WHEN 'high' THEN 2
                       WHEN 'normal' THEN 3
                       WHEN 'low' THEN 4
                   END,
                   created_at ASC""",
            (guild_id,)
        )
        return [dict(row) for row in rows]

    def claim_ticket(self, ticket_id: str, staff_id: int) -> bool:
        """
        Claim a ticket for handling.

        Args:
            ticket_id: Ticket ID to claim.
            staff_id: Staff member claiming the ticket.

        Returns:
            True if claimed successfully.
        """
        import time
        cursor = self.execute(
            """UPDATE tickets
               SET status = 'claimed', claimed_by = ?, claimed_at = ?
               WHERE ticket_id = ? AND status = 'open'""",
            (staff_id, time.time(), ticket_id)
        )

        if cursor.rowcount > 0:
            logger.tree("Ticket Claimed", [
                ("Ticket ID", ticket_id),
                ("Staff ID", str(staff_id)),
            ], emoji="✋")
            return True
        return False

    def unclaim_ticket(self, ticket_id: str) -> bool:
        """
        Unclaim a ticket.

        Args:
            ticket_id: Ticket ID to unclaim.

        Returns:
            True if unclaimed successfully.
        """
        cursor = self.execute(
            """UPDATE tickets
               SET status = 'open', claimed_by = NULL
               WHERE ticket_id = ? AND status = 'claimed'""",
            (ticket_id,)
        )
        return cursor.rowcount > 0

    def assign_ticket(self, ticket_id: str, staff_id: int) -> bool:
        """
        Assign a ticket to a staff member.

        Args:
            ticket_id: Ticket ID to assign.
            staff_id: Staff member to assign to.

        Returns:
            True if assigned successfully.
        """
        cursor = self.execute(
            """UPDATE tickets
               SET assigned_to = ?
               WHERE ticket_id = ?""",
            (staff_id, ticket_id)
        )

        if cursor.rowcount > 0:
            logger.tree("Ticket Assigned", [
                ("Ticket ID", ticket_id),
                ("Assigned To", str(staff_id)),
            ], emoji="👤")
            return True
        return False

    def set_ticket_priority(self, ticket_id: str, priority: str) -> bool:
        """
        Set ticket priority.

        Args:
            ticket_id: Ticket ID.
            priority: New priority (low, normal, high, urgent).

        Returns:
            True if updated successfully.
        """
        if priority not in ("low", "normal", "high", "urgent"):
            return False

        cursor = self.execute(
            "UPDATE tickets SET priority = ? WHERE ticket_id = ?",
            (priority, ticket_id)
        )

        if cursor.rowcount > 0:
            logger.tree("Ticket Priority Set", [
                ("Ticket ID", ticket_id),
                ("Priority", priority),
            ], emoji="🔔")
            return True
        return False

    def close_ticket(
        self,
        ticket_id: str,
        closed_by: int,
        close_reason: Optional[str] = None,
    ) -> bool:
        """
        Close a ticket.

        Args:
            ticket_id: Ticket ID to close.
            closed_by: Staff member closing the ticket.
            close_reason: Optional reason for closing.

        Returns:
            True if closed successfully.
        """
        cursor = self.execute(
            """UPDATE tickets
               SET status = 'closed',
                   closed_at = ?,
                   closed_by = ?,
                   close_reason = ?
               WHERE ticket_id = ? AND status != 'closed'""",
            (time.time(), closed_by, close_reason, ticket_id)
        )

        if cursor.rowcount > 0:
            logger.tree("Ticket Closed", [
                ("Ticket ID", ticket_id),
                ("Closed By", str(closed_by)),
                ("Reason", close_reason or "No reason"),
            ], emoji="🔒")
            return True
        return False

    def reopen_ticket(self, ticket_id: str) -> bool:
        """
        Reopen a closed ticket.

        Args:
            ticket_id: Ticket ID to reopen.

        Returns:
            True if reopened successfully.
        """
        cursor = self.execute(
            """UPDATE tickets
               SET status = 'open',
                   closed_at = NULL,
                   closed_by = NULL,
                   close_reason = NULL
               WHERE ticket_id = ? AND status = 'closed'""",
            (ticket_id,)
        )

        if cursor.rowcount > 0:
            logger.tree("Ticket Reopened", [
                ("Ticket ID", ticket_id),
            ], emoji="🔓")
            return True
        return False

    def get_ticket_stats(self, guild_id: int) -> Dict[str, int]:
        """
        Get ticket statistics for a guild.

        Args:
            guild_id: Guild ID.

        Returns:
            Dict with open, claimed, closed counts.
        """
        open_count = self.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND status = 'open'",
            (guild_id,)
        )
        claimed_count = self.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND status = 'claimed'",
            (guild_id,)
        )
        closed_count = self.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND status = 'closed'",
            (guild_id,)
        )

        return {
            "open": open_count["c"] if open_count else 0,
            "claimed": claimed_count["c"] if claimed_count else 0,
            "closed": closed_count["c"] if closed_count else 0,
        }

    def get_average_response_time(self, guild_id: int, days: int = 30) -> Optional[float]:
        """
        Get average ticket response time (time from creation to first claim).

        Args:
            guild_id: Guild ID.
            days: Number of days to look back (default 30).

        Returns:
            Average response time in seconds, or None if no data.
        """
        import time
        cutoff = time.time() - (days * 24 * 60 * 60)

        row = self.fetchone(
            """SELECT AVG(claimed_at - created_at) as avg_time
               FROM tickets
               WHERE guild_id = ?
               AND claimed_at IS NOT NULL
               AND created_at > ?
               AND (claimed_at - created_at) > 0
               AND (claimed_at - created_at) < 604800""",  # Exclude outliers > 7 days
            (guild_id, cutoff)
        )

        if row and row["avg_time"] is not None:
            return row["avg_time"]
        return None

    def get_open_ticket_position(self, ticket_id: str, guild_id: int) -> int:
        """
        Get the position of a ticket in the queue (how many open tickets are ahead).

        Args:
            ticket_id: The ticket ID to check.
            guild_id: Guild ID.

        Returns:
            Number of tickets ahead in queue (0 = first in line).
        """
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return 0

        row = self.fetchone(
            """SELECT COUNT(*) as c FROM tickets
               WHERE guild_id = ?
               AND status = 'open'
               AND created_at < ?""",
            (guild_id, ticket["created_at"])
        )

        return row["c"] if row else 0

    def get_user_open_ticket_count(self, user_id: int, guild_id: int) -> int:
        """
        Count open tickets for a user.

        Args:
            user_id: User ID.
            guild_id: Guild ID.

        Returns:
            Number of open tickets.
        """
        row = self.fetchone(
            """SELECT COUNT(*) as c FROM tickets
               WHERE user_id = ? AND guild_id = ? AND status IN ('open', 'claimed')""",
            (user_id, guild_id)
        )
        return row["c"] if row else 0

    def update_ticket_activity(self, ticket_id: str) -> bool:
        """
        Update last activity timestamp for a ticket.

        Args:
            ticket_id: Ticket ID.

        Returns:
            True if updated.
        """
        cursor = self.execute(
            "UPDATE tickets SET last_activity_at = ? WHERE ticket_id = ?",
            (time.time(), ticket_id)
        )
        return cursor.rowcount > 0

    def get_inactive_tickets(
        self,
        guild_id: int,
        inactive_since: float,
    ) -> List[TicketRecord]:
        """
        Get tickets with no activity since a given timestamp.

        Args:
            guild_id: Guild ID.
            inactive_since: Unix timestamp - tickets inactive since before this.

        Returns:
            List of inactive ticket records.
        """
        rows = self.fetchall(
            """SELECT * FROM tickets
               WHERE guild_id = ? AND status IN ('open', 'claimed')
               AND (last_activity_at IS NULL OR last_activity_at < ?)
               AND (created_at < ?)
               ORDER BY last_activity_at ASC""",
            (guild_id, inactive_since, inactive_since)
        )
        return [TicketRecord(**dict(row)) for row in rows]

    def get_unwarned_inactive_tickets(
        self,
        guild_id: int,
        inactive_since: float,
    ) -> List[TicketRecord]:
        """
        Get inactive tickets that haven't been warned yet.

        Args:
            guild_id: Guild ID.
            inactive_since: Unix timestamp - tickets inactive since before this.

        Returns:
            List of unwarned inactive ticket records.
        """
        rows = self.fetchall(
            """SELECT * FROM tickets
               WHERE guild_id = ? AND status IN ('open', 'claimed')
               AND (last_activity_at IS NULL OR last_activity_at < ?)
               AND (created_at < ?)
               AND warned_at IS NULL
               ORDER BY last_activity_at ASC""",
            (guild_id, inactive_since, inactive_since)
        )
        return [TicketRecord(**dict(row)) for row in rows]

    def get_warned_tickets_ready_to_close(
        self,
        guild_id: int,
        warned_before: float,
    ) -> List[TicketRecord]:
        """
        Get tickets that were warned and are now ready to auto-close.

        Args:
            guild_id: Guild ID.
            warned_before: Unix timestamp - tickets warned before this time.

        Returns:
            List of ticket records ready to auto-close.
        """
        rows = self.fetchall(
            """SELECT * FROM tickets
               WHERE guild_id = ? AND status IN ('open', 'claimed')
               AND warned_at IS NOT NULL AND warned_at < ?
               ORDER BY warned_at ASC""",
            (guild_id, warned_before)
        )
        return [TicketRecord(**dict(row)) for row in rows]

    def get_closed_tickets_ready_to_delete(
        self,
        guild_id: int,
        closed_before: float,
    ) -> List[TicketRecord]:
        """
        Get closed tickets that are ready for deletion.

        Args:
            guild_id: Guild ID.
            closed_before: Unix timestamp - tickets closed before this time.

        Returns:
            List of closed ticket records ready to delete.
        """
        rows = self.fetchall(
            """SELECT * FROM tickets
               WHERE guild_id = ? AND status = 'closed'
               AND closed_at IS NOT NULL AND closed_at < ?
               ORDER BY closed_at ASC""",
            (guild_id, closed_before)
        )
        return [TicketRecord(**dict(row)) for row in rows]

    def delete_ticket(self, ticket_id: str) -> bool:
        """
        Delete a ticket from the database.

        Args:
            ticket_id: Ticket ID.

        Returns:
            True if deleted.
        """
        cursor = self.execute(
            "DELETE FROM tickets WHERE ticket_id = ?",
            (ticket_id,)
        )
        return cursor.rowcount > 0

    def mark_ticket_warned(self, ticket_id: str) -> bool:
        """
        Mark a ticket as warned about inactivity.

        Args:
            ticket_id: Ticket ID.

        Returns:
            True if updated.
        """
        cursor = self.execute(
            "UPDATE tickets SET warned_at = ? WHERE ticket_id = ?",
            (time.time(), ticket_id)
        )
        return cursor.rowcount > 0

    def clear_ticket_warning(self, ticket_id: str) -> bool:
        """
        Clear inactivity warning (when user responds).

        Args:
            ticket_id: Ticket ID.

        Returns:
            True if updated.
        """
        cursor = self.execute(
            "UPDATE tickets SET warned_at = NULL WHERE ticket_id = ?",
            (ticket_id,)
        )
        return cursor.rowcount > 0

    def save_ticket_transcript(self, ticket_id: str, html_content: str) -> bool:
        """
        Save HTML transcript for a ticket.

        Args:
            ticket_id: Ticket ID.
            html_content: HTML transcript content.

        Returns:
            True if saved successfully.
        """
        cursor = self.execute(
            "UPDATE tickets SET transcript_html = ? WHERE ticket_id = ?",
            (html_content, ticket_id)
        )
        return cursor.rowcount > 0

    def get_ticket_transcript(self, ticket_id: str) -> Optional[str]:
        """
        Get HTML transcript for a ticket.

        Args:
            ticket_id: Ticket ID.

        Returns:
            HTML content or None if not found.
        """
        row = self.fetchone(
            "SELECT transcript_html FROM tickets WHERE ticket_id = ?",
            (ticket_id,)
        )
        return row["transcript_html"] if row and row["transcript_html"] else None

    def set_control_panel_message(self, ticket_id: str, message_id: int) -> bool:
        """
        Set the control panel message ID for a ticket.

        Args:
            ticket_id: Ticket ID.
            message_id: Discord message ID of the control panel.

        Returns:
            True if successful.
        """
        cursor = self.execute(
            "UPDATE tickets SET control_panel_message_id = ? WHERE ticket_id = ?",
            (message_id, ticket_id)
        )
        return cursor.rowcount > 0

    def clear_close_request(self, ticket_id: str) -> bool:
        """
        Clear close request status for a ticket.

        This is a no-op for database since close requests are tracked in memory.
        Kept for API compatibility.

        Args:
            ticket_id: Ticket ID.

        Returns:
            True always.
        """
        return True

    # =========================================================================
    # Modmail Operations
    # =========================================================================

    def create_modmail(
        self,
        user_id: int,
        guild_id: int,
        thread_id: int,
    ) -> None:
        """
        Create a modmail entry for a banned user.

        Args:
            user_id: Discord user ID (banned user).
            guild_id: Guild ID they're banned from.
            thread_id: Forum thread ID for this modmail.
        """
        now = time.time()
        self.execute(
            """
            INSERT OR REPLACE INTO modmail
            (user_id, guild_id, thread_id, status, created_at)
            VALUES (?, ?, ?, 'open', ?)
            """,
            (user_id, guild_id, thread_id, now)
        )

    def get_modmail_by_user(self, user_id: int, guild_id: int) -> Optional[Dict]:
        """
        Get modmail entry for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Modmail record dict or None.
        """
        result = self.fetch_one(
            "SELECT * FROM modmail WHERE user_id = ? AND guild_id = ? AND status = 'open'",
            (user_id, guild_id)
        )
        return dict(result) if result else None

    def get_modmail_by_thread(self, thread_id: int) -> Optional[Dict]:
        """
        Get modmail entry by thread ID.

        Args:
            thread_id: Thread ID.

        Returns:
            Modmail record dict or None.
        """
        result = self.fetch_one(
            "SELECT * FROM modmail WHERE thread_id = ?",
            (thread_id,)
        )
        return dict(result) if result else None

    def close_modmail(self, thread_id: int, closed_by: int) -> bool:
        """
        Close a modmail thread.

        Args:
            thread_id: Thread ID.
            closed_by: Staff member who closed it.

        Returns:
            True if updated.
        """
        now = time.time()
        cursor = self.execute(
            """
            UPDATE modmail
            SET status = 'closed', closed_at = ?, closed_by = ?
            WHERE thread_id = ?
            """,
            (now, closed_by, thread_id)
        )
        return cursor.rowcount > 0

    def reopen_modmail(self, user_id: int, guild_id: int) -> bool:
        """
        Reopen a closed modmail.

        Args:
            user_id: User ID.
            guild_id: Guild ID.

        Returns:
            True if updated.
        """
        cursor = self.execute(
            """
            UPDATE modmail
            SET status = 'open', closed_at = NULL, closed_by = NULL
            WHERE user_id = ? AND guild_id = ?
            """,
            (user_id, guild_id)
        )
        return cursor.rowcount > 0


    # =========================================================================
    # Stats API Helper Methods
    # =========================================================================

    def get_mutes_in_range(self, start_ts: float, end_ts: float, guild_id: Optional[int] = None) -> int:
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

    def get_bans_in_range(self, start_ts: float, end_ts: float, guild_id: Optional[int] = None) -> int:
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

    def get_warns_in_range(self, start_ts: float, end_ts: float, guild_id: Optional[int] = None) -> int:
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

    def get_total_mutes(self, guild_id: Optional[int] = None) -> int:
        """Get total mute count."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM mute_history WHERE action = 'mute' AND guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM mute_history WHERE action = 'mute'")
        return row["count"] if row else 0

    def get_total_bans(self, guild_id: Optional[int] = None) -> int:
        """Get total ban count."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM ban_history WHERE action = 'ban' AND guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM ban_history WHERE action = 'ban'")
        return row["count"] if row else 0

    def get_total_warns(self, guild_id: Optional[int] = None) -> int:
        """Get total warning count."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM warnings WHERE guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM warnings")
        return row["count"] if row else 0

    def get_total_cases(self, guild_id: Optional[int] = None) -> int:
        """Get total case count."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM cases WHERE guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM cases")
        return row["count"] if row else 0

    def get_active_prisoners_count(self, guild_id: Optional[int] = None) -> int:
        """Get count of currently active mutes."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM active_mutes WHERE unmuted = 0 AND guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM active_mutes WHERE unmuted = 0")
        return row["count"] if row else 0

    def get_open_cases_count(self, guild_id: Optional[int] = None) -> int:
        """Get count of open cases."""
        if guild_id:
            row = self.fetchone(
                "SELECT COUNT(*) as count FROM cases WHERE status = 'open' AND guild_id = ?",
                (guild_id,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as count FROM cases WHERE status = 'open'")
        return row["count"] if row else 0

    def get_top_offenders(self, limit: int = 10, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
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

    def get_recent_actions(self, limit: int = 10, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
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

    def get_moderator_stats(self, moderator_id: int, guild_id: Optional[int] = None) -> Dict[str, Any]:
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

    def get_moderator_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get moderator leaderboard by action count."""
        rows = self.fetchall(
            """
            SELECT mod_id as moderator_id, action_count, last_action_at
            FROM mod_tracker
            ORDER BY action_count DESC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in rows] if rows else []

    def get_repeat_offenders(self, min_offenses: int = 3, limit: int = 5, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get users with 3+ total punishments (repeat offenders)."""
        guild_filter = "AND guild_id = ?" if guild_id else ""
        params = [guild_id] if guild_id else []

        rows = self.fetchall(
            f"""
            SELECT
                user_id,
                SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns,
                COUNT(*) as total
            FROM (
                SELECT user_id, 'mute' as action_type, guild_id FROM mute_history WHERE 1=1 {guild_filter}
                UNION ALL
                SELECT user_id, 'ban' as action_type, guild_id FROM ban_history WHERE 1=1 {guild_filter}
                UNION ALL
                SELECT user_id, 'warn' as action_type, guild_id FROM warnings WHERE 1=1 {guild_filter}
            )
            GROUP BY user_id
            HAVING total >= ?
            ORDER BY total DESC
            LIMIT ?
            """,
            (*params, *params, *params, min_offenses, limit)
        )
        return [dict(row) for row in rows] if rows else []

    def get_recent_releases(self, limit: int = 5, guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get recently released prisoners (unmuted users)."""
        guild_filter = "WHERE guild_id = ?" if guild_id else ""
        params = (guild_id, limit) if guild_id else (limit,)

        # Note: active_mutes doesn't have unmuted_at, so we use expires_at as proxy
        # For manual unmutes, expires_at would be the scheduled time
        rows = self.fetchall(
            f"""
            SELECT
                user_id,
                muted_at,
                expires_at,
                CAST((COALESCE(expires_at, strftime('%s', 'now')) - muted_at) / 60 AS INTEGER) as duration_minutes
            FROM active_mutes
            {guild_filter}
            {"AND" if guild_filter else "WHERE"} unmuted = 1
            ORDER BY expires_at DESC
            LIMIT ?
            """,
            params
        )
        return [dict(row) for row in rows] if rows else []

    def get_weekly_top_moderator(self, guild_id: Optional[int] = None, exclude_user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get the top moderator for this week based on actions.

        Args:
            guild_id: Optional guild ID to filter by
            exclude_user_id: Optional user ID to exclude (e.g., the bot itself)
        """
        import time
        week_start = time.time() - (7 * 24 * 60 * 60)
        guild_filter = "AND guild_id = ?" if guild_id else ""
        exclude_filter = "WHERE moderator_id != ?" if exclude_user_id else ""

        # Build params for each subquery (3 subqueries) plus optional exclusion
        params: list = []
        for _ in range(3):
            params.append(week_start)
            if guild_id:
                params.append(guild_id)
        if exclude_user_id:
            params.append(exclude_user_id)

        row = self.fetchone(
            f"""
            SELECT
                moderator_id,
                COUNT(*) as weekly_actions,
                SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
                SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
                SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
            FROM (
                SELECT moderator_id, 'mute' as action_type, guild_id, timestamp as ts
                FROM mute_history WHERE timestamp >= ? {guild_filter}
                UNION ALL
                SELECT moderator_id, 'ban' as action_type, guild_id, timestamp as ts
                FROM ban_history WHERE timestamp >= ? {guild_filter}
                UNION ALL
                SELECT moderator_id, 'warn' as action_type, guild_id, created_at as ts
                FROM warnings WHERE created_at >= ? {guild_filter}
            )
            {exclude_filter}
            GROUP BY moderator_id
            ORDER BY weekly_actions DESC
            LIMIT 1
            """,
            tuple(params)
        )
        return dict(row) if row else None


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
