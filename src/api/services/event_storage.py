"""
AzabBot - Event Storage
=======================

SQLite-based storage for Discord events (bans, kicks, message deletes, etc.)
with user avatars and comprehensive filtering for dashboard display.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

TIMEZONE = ZoneInfo("America/New_York")
DB_PATH = Path("data/events.db")
DEFAULT_RETENTION_DAYS = 30
MAX_QUERY_LIMIT = 500


# =============================================================================
# Event Types
# =============================================================================

class EventType:
    """Discord event types."""
    # Member events
    MEMBER_BAN = "member.ban"
    MEMBER_UNBAN = "member.unban"
    MEMBER_KICK = "member.kick"
    MEMBER_TIMEOUT = "member.timeout"
    MEMBER_TIMEOUT_REMOVE = "member.timeout_remove"
    MEMBER_JOIN = "member.join"
    MEMBER_LEAVE = "member.leave"
    MEMBER_ROLE_ADD = "member.role_add"
    MEMBER_ROLE_REMOVE = "member.role_remove"
    MEMBER_NICK_CHANGE = "member.nick_change"
    MEMBER_WARN = "member.warn"
    MEMBER_FORBID = "member.forbid"
    MEMBER_UNFORBID = "member.unforbid"

    # Message events
    MESSAGE_DELETE = "message.delete"
    MESSAGE_BULK_DELETE = "message.bulk_delete"
    MESSAGE_EDIT = "message.edit"

    # Voice events
    VOICE_DISCONNECT = "voice.disconnect"
    VOICE_MUTE = "voice.mute"
    VOICE_DEAFEN = "voice.deafen"

    # Channel events
    CHANNEL_CREATE = "channel.create"
    CHANNEL_DELETE = "channel.delete"
    CHANNEL_UPDATE = "channel.update"

    # Role events
    ROLE_CREATE = "role.create"
    ROLE_DELETE = "role.delete"
    ROLE_UPDATE = "role.update"

    # Server events
    SERVER_UPDATE = "server.update"
    SERVER_LOCKDOWN = "server.lockdown"
    SERVER_UNLOCK = "server.unlock"
    SERVER_QUARANTINE = "server.quarantine"
    SERVER_UNQUARANTINE = "server.unquarantine"

    # Bot events
    BOT_ADD = "bot.add"
    WEBHOOK_CREATE = "webhook.create"
    WEBHOOK_DELETE = "webhook.delete"

    @classmethod
    def all_types(cls) -> List[str]:
        """Get all event types."""
        return [
            v for k, v in vars(cls).items()
            if not k.startswith('_') and isinstance(v, str) and '.' in v
        ]

    @classmethod
    def categories(cls) -> Dict[str, List[str]]:
        """Get event types grouped by category."""
        return {
            "member": [
                cls.MEMBER_BAN, cls.MEMBER_UNBAN, cls.MEMBER_KICK,
                cls.MEMBER_TIMEOUT, cls.MEMBER_TIMEOUT_REMOVE,
                cls.MEMBER_JOIN, cls.MEMBER_LEAVE,
                cls.MEMBER_ROLE_ADD, cls.MEMBER_ROLE_REMOVE,
                cls.MEMBER_NICK_CHANGE, cls.MEMBER_WARN,
                cls.MEMBER_FORBID, cls.MEMBER_UNFORBID,
            ],
            "message": [
                cls.MESSAGE_DELETE, cls.MESSAGE_BULK_DELETE, cls.MESSAGE_EDIT,
            ],
            "voice": [
                cls.VOICE_DISCONNECT, cls.VOICE_MUTE, cls.VOICE_DEAFEN,
            ],
            "channel": [
                cls.CHANNEL_CREATE, cls.CHANNEL_DELETE, cls.CHANNEL_UPDATE,
            ],
            "role": [
                cls.ROLE_CREATE, cls.ROLE_DELETE, cls.ROLE_UPDATE,
            ],
            "server": [
                cls.SERVER_UPDATE, cls.BOT_ADD,
                cls.WEBHOOK_CREATE, cls.WEBHOOK_DELETE,
                cls.SERVER_LOCKDOWN, cls.SERVER_UNLOCK,
                cls.SERVER_QUARANTINE, cls.SERVER_UNQUARANTINE,
            ],
        }


# =============================================================================
# Event Model
# =============================================================================

@dataclass
class StoredEvent:
    """A stored Discord event."""
    id: int
    timestamp: datetime
    event_type: str
    guild_id: int

    # Actor (who performed the action)
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    actor_avatar: Optional[str] = None

    # Target (who was affected)
    target_id: Optional[int] = None
    target_name: Optional[str] = None
    target_avatar: Optional[str] = None

    # Context
    channel_id: Optional[int] = None
    channel_name: Optional[str] = None

    # Details
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response dict."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "guild_id": str(self.guild_id),
            "actor": {
                "id": str(self.actor_id) if self.actor_id else None,
                "name": self.actor_name,
                "avatar": self.actor_avatar,
            } if self.actor_id else None,
            "target": {
                "id": str(self.target_id) if self.target_id else None,
                "name": self.target_name,
                "avatar": self.target_avatar,
            } if self.target_id else None,
            "channel": {
                "id": str(self.channel_id) if self.channel_id else None,
                "name": self.channel_name,
            } if self.channel_id else None,
            "reason": self.reason,
            "details": self.details,
        }


# =============================================================================
# Event Storage Service
# =============================================================================

class EventStorage:
    """
    SQLite-based persistent event storage.

    Features:
    - Store Discord events with user info and avatars
    - Filter by event type, user, moderator, channel
    - Full-text search on reasons and details
    - Automatic retention cleanup
    - Thread-safe operations
    """

    def __init__(self, db_path: Path = DB_PATH, retention_days: int = DEFAULT_RETENTION_DAYS):
        self._db_path = db_path
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._on_event_callback: Optional[Callable[[Dict[str, Any]], None]] = None

        # Ensure data directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    def set_on_event(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Set callback to be called when events are added (for WebSocket broadcast)."""
        self._on_event_callback = callback

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

                # Create events table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        guild_id INTEGER NOT NULL,

                        actor_id INTEGER,
                        actor_name TEXT,
                        actor_avatar TEXT,

                        target_id INTEGER,
                        target_name TEXT,
                        target_avatar TEXT,

                        channel_id INTEGER,
                        channel_name TEXT,

                        reason TEXT,
                        details TEXT,

                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes for fast queries
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_actor ON events(actor_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_target ON events(target_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_guild ON events(guild_id)")

                # Create FTS5 virtual table for full-text search
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                        reason,
                        actor_name,
                        target_name,
                        channel_name,
                        details,
                        content='events',
                        content_rowid='id'
                    )
                """)

                # Create triggers to keep FTS in sync
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
                        INSERT INTO events_fts(rowid, reason, actor_name, target_name, channel_name, details)
                        VALUES (new.id, new.reason, new.actor_name, new.target_name, new.channel_name, new.details);
                    END
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
                        INSERT INTO events_fts(events_fts, rowid, reason, actor_name, target_name, channel_name, details)
                        VALUES('delete', old.id, old.reason, old.actor_name, old.target_name, old.channel_name, old.details);
                    END
                """)

                conn.commit()

                logger.tree("Event Storage Initialized", [
                    ("Database", str(self._db_path)),
                    ("Retention", f"{self._retention_days} days"),
                ], emoji="📋")

            finally:
                conn.close()

    # =========================================================================
    # Write Operations
    # =========================================================================

    def add(
        self,
        event_type: str,
        guild_id: int,
        actor_id: Optional[int] = None,
        actor_name: Optional[str] = None,
        actor_avatar: Optional[str] = None,
        target_id: Optional[int] = None,
        target_name: Optional[str] = None,
        target_avatar: Optional[str] = None,
        channel_id: Optional[int] = None,
        channel_name: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Add an event to storage.

        Returns:
            The ID of the inserted event.
        """
        timestamp = datetime.now(TIMEZONE).replace(tzinfo=None).isoformat()
        details_json = json.dumps(details) if details else None

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO events (
                        timestamp, event_type, guild_id,
                        actor_id, actor_name, actor_avatar,
                        target_id, target_name, target_avatar,
                        channel_id, channel_name,
                        reason, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp, event_type, guild_id,
                        actor_id, actor_name, actor_avatar,
                        target_id, target_name, target_avatar,
                        channel_id, channel_name,
                        reason, details_json,
                    )
                )
                conn.commit()
                event_id = cursor.lastrowid or 0

                # Trigger WebSocket broadcast callback if set
                if self._on_event_callback and event_id:
                    try:
                        event_data = StoredEvent(
                            id=event_id,
                            timestamp=datetime.fromisoformat(timestamp),
                            event_type=event_type,
                            guild_id=guild_id,
                            actor_id=actor_id,
                            actor_name=actor_name,
                            actor_avatar=actor_avatar,
                            target_id=target_id,
                            target_name=target_name,
                            target_avatar=target_avatar,
                            channel_id=channel_id,
                            channel_name=channel_name,
                            reason=reason,
                            details=details or {},
                        )
                        self._on_event_callback(event_data.to_dict())
                    except (AttributeError, TypeError, RuntimeError):
                        pass  # Don't let callback errors break event storage

                return event_id
            finally:
                conn.close()

    def cleanup_old_events(self) -> int:
        """
        Delete events older than retention period.

        Returns:
            Number of deleted events.
        """
        cutoff = datetime.now(TIMEZONE) - timedelta(days=self._retention_days)
        cutoff_str = cutoff.replace(tzinfo=None).isoformat()

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM events WHERE timestamp < ?", (cutoff_str,))
                deleted = cursor.rowcount
                conn.commit()

                # Rebuild FTS index
                if deleted > 0:
                    cursor.execute("INSERT INTO events_fts(events_fts) VALUES('rebuild')")
                    conn.commit()

                return deleted
            finally:
                conn.close()

    # =========================================================================
    # Read Operations
    # =========================================================================

    def get_events(
        self,
        limit: int = 100,
        offset: int = 0,
        event_type: Optional[str] = None,
        event_category: Optional[str] = None,
        actor_id: Optional[int] = None,
        target_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        search: Optional[str] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> Tuple[List[StoredEvent], int]:
        """
        Query events with filtering.

        Returns:
            Tuple of (events, total_count)
        """
        limit = min(limit, MAX_QUERY_LIMIT)

        conditions = []
        params: List[Any] = []

        # Event type filter
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        # Event category filter (e.g., "member" for all member events)
        if event_category:
            categories = EventType.categories()
            if event_category in categories:
                placeholders = ",".join("?" * len(categories[event_category]))
                conditions.append(f"event_type IN ({placeholders})")
                params.extend(categories[event_category])

        # Actor filter
        if actor_id:
            conditions.append("actor_id = ?")
            params.append(actor_id)

        # Target filter
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)

        # Channel filter
        if channel_id:
            conditions.append("channel_id = ?")
            params.append(channel_id)

        # Guild filter
        if guild_id:
            conditions.append("guild_id = ?")
            params.append(guild_id)

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
            conditions.append("id IN (SELECT rowid FROM events_fts WHERE events_fts MATCH ?)")
            search_term = search.replace('"', '""')
            params.append(f'"{search_term}"*')

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                # Get total count
                cursor.execute(f"SELECT COUNT(*) FROM events WHERE {where_clause}", params)
                total = cursor.fetchone()[0]

                # Get events
                cursor.execute(
                    f"""
                    SELECT id, timestamp, event_type, guild_id,
                           actor_id, actor_name, actor_avatar,
                           target_id, target_name, target_avatar,
                           channel_id, channel_name,
                           reason, details
                    FROM events
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset]
                )

                events = []
                for row in cursor.fetchall():
                    details = {}
                    if row["details"]:
                        try:
                            details = json.loads(row["details"])
                        except json.JSONDecodeError:
                            pass

                    events.append(StoredEvent(
                        id=row["id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        event_type=row["event_type"],
                        guild_id=row["guild_id"],
                        actor_id=row["actor_id"],
                        actor_name=row["actor_name"],
                        actor_avatar=row["actor_avatar"],
                        target_id=row["target_id"],
                        target_name=row["target_name"],
                        target_avatar=row["target_avatar"],
                        channel_id=row["channel_id"],
                        channel_name=row["channel_name"],
                        reason=row["reason"],
                        details=details,
                    ))

                return events, total
            finally:
                conn.close()

    def get_stats(self, guild_id: Optional[int] = None) -> Dict[str, Any]:
        """Get event statistics."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()

                guild_filter = "WHERE guild_id = ?" if guild_id else ""
                params = [guild_id] if guild_id else []

                # Total count
                cursor.execute(f"SELECT COUNT(*) FROM events {guild_filter}", params)
                total = cursor.fetchone()[0]

                # Count by event type
                cursor.execute(f"""
                    SELECT event_type, COUNT(*) as count
                    FROM events
                    {guild_filter}
                    GROUP BY event_type
                    ORDER BY count DESC
                """, params)
                by_type = {row["event_type"]: row["count"] for row in cursor.fetchall()}

                # Count by category
                by_category = {}
                categories = EventType.categories()
                for category, types in categories.items():
                    by_category[category] = sum(by_type.get(t, 0) for t in types)

                # Recent activity (last 24h by hour)
                yesterday = (datetime.now(TIMEZONE) - timedelta(days=1)).replace(tzinfo=None).isoformat()
                cursor.execute(f"""
                    SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
                    FROM events
                    WHERE timestamp >= ?
                    {"AND guild_id = ?" if guild_id else ""}
                    GROUP BY hour
                    ORDER BY hour
                """, [yesterday] + params)
                by_hour = {row["hour"]: row["count"] for row in cursor.fetchall()}

                # Top moderators (actors)
                cursor.execute(f"""
                    SELECT actor_id, actor_name, actor_avatar, COUNT(*) as count
                    FROM events
                    WHERE actor_id IS NOT NULL
                    {"AND guild_id = ?" if guild_id else ""}
                    GROUP BY actor_id
                    ORDER BY count DESC
                    LIMIT 10
                """, params)
                top_actors = [
                    {
                        "id": str(row["actor_id"]),
                        "name": row["actor_name"],
                        "avatar": row["actor_avatar"],
                        "count": row["count"],
                    }
                    for row in cursor.fetchall()
                ]

                return {
                    "total": total,
                    "by_type": by_type,
                    "by_category": by_category,
                    "by_hour": by_hour,
                    "top_actors": top_actors,
                    "retention_days": self._retention_days,
                }
            finally:
                conn.close()

    def get_event_types(self) -> List[Dict[str, Any]]:
        """Get all event types with counts."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT event_type, COUNT(*) as count
                    FROM events
                    GROUP BY event_type
                    ORDER BY count DESC
                """)
                return [
                    {"type": row["event_type"], "count": row["count"]}
                    for row in cursor.fetchall()
                ]
            finally:
                conn.close()


# =============================================================================
# Singleton
# =============================================================================

_storage: Optional[EventStorage] = None


def get_event_storage() -> EventStorage:
    """Get the event storage singleton."""
    global _storage
    if _storage is None:
        _storage = EventStorage()
    return _storage


__all__ = ["EventStorage", "StoredEvent", "EventType", "get_event_storage"]
