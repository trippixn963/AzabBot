# =============================================================================
# SaydnayaBot - Prisoner Database Service
# =============================================================================
# Manages prisoner tracking, conversation history, and report generation
# for Azab's psychological torture operations. Provides memory persistence
# and analytics capabilities.
# =============================================================================

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    DatabaseQueryError,
)
from src.services.base_service import BaseService, HealthCheckResult, ServiceStatus


@dataclass
class Prisoner:
    """Prisoner data model."""

    discord_id: str
    username: str
    display_name: Optional[str] = None
    total_messages: int = 0
    total_sessions: int = 0
    psychological_profile: Optional[str] = None
    vulnerability_notes: Optional[str] = None
    mute_reason: Optional[str] = None
    mute_reason_extracted: bool = False
    torture_effectiveness_score: float = 0.0
    status: str = "active"
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    id: Optional[int] = None


@dataclass
class TortureSession:
    """Torture session data model."""

    prisoner_id: int
    channel_id: str
    channel_name: Optional[str] = None
    message_count: int = 0
    confusion_level: int = 0
    topics_discussed: List[str] = None
    torture_methods: List[str] = None
    session_notes: Optional[str] = None
    effectiveness_rating: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    id: Optional[int] = None

    def __post_init__(self):
        if self.topics_discussed is None:
            self.topics_discussed = []
        if self.torture_methods is None:
            self.torture_methods = []


@dataclass
class ConversationMessage:
    """Conversation message data model."""

    session_id: int
    prisoner_id: int
    message_type: str  # 'prisoner' or 'azab'
    content: str
    confusion_technique: Optional[str] = None
    emotional_state: Optional[str] = None
    timestamp: Optional[datetime] = None
    id: Optional[int] = None


class PrisonerDatabaseService(BaseService):
    """
    Database service for tracking prisoners and their torture sessions.

    Features:
    - Prisoner profile management
    - Conversation history tracking
    - Session analytics
    - Psychological profiling
    - Report generation
    - Performance metrics
    """

    def __init__(self, name: str = "PrisonerDatabaseService"):
        """Initialize the database service."""
        super().__init__(name, dependencies=[])

        self.db_path: Optional[Path] = None
        self.connection: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

        # Cache for active sessions
        self._active_sessions: Dict[str, TortureSession] = {}

        # Performance metrics
        self._total_queries = 0
        self._failed_queries = 0

    async def initialize(self, config: Dict[str, Any], **kwargs) -> None:
        """
        Initialize the database service.

        Args:
            config: Service configuration
        """
        # Set up database path
        db_dir = Path(config.get("DATABASE_DIR", "data"))
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / "prisoners.db"

        # Create database and schema
        await self._create_database()

        self.logger.log_info(f"Database initialized at {self.db_path}")

    async def start(self) -> None:
        """Start the database service."""
        # Test database connection
        async with self._get_connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM prisoners")
            count = await cursor.fetchone()
            self.logger.log_info(f"Database started with {count[0]} prisoners")

    async def stop(self) -> None:
        """Stop the database service."""
        # Close active sessions
        for session in self._active_sessions.values():
            await self.end_torture_session(session.id)

        self.logger.log_info("Database service stopped")

    async def health_check(self) -> HealthCheckResult:
        """Perform health check on the database service."""
        try:
            async with self._get_connection() as conn:
                await conn.execute("SELECT 1")

            success_rate = self._calculate_success_rate()

            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Database operational",
                details={
                    "total_queries": self._total_queries,
                    "failed_queries": self._failed_queries,
                    "success_rate": f"{success_rate:.1f}%",
                    "active_sessions": len(self._active_sessions),
                },
            )

        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Database health check failed: {str(e)}",
            )

    async def _create_database(self):
        """Create database tables from schema."""
        schema_path = Path(__file__).parent.parent / "database" / "schema.sql"

        if not schema_path.exists():
            raise DatabaseError(f"Schema file not found: {schema_path}")

        try:
            async with self._get_connection() as conn:
                with open(schema_path, "r") as f:
                    schema = f.read()

                await conn.executescript(schema)
                await conn.commit()

        except Exception as e:
            raise DatabaseConnectionError(f"Failed to create database: {str(e)}") from e

    @asynccontextmanager
    async def _get_connection(self):
        """Get database connection with async context manager."""
        async with self._lock:
            try:
                conn = await asyncio.get_event_loop().run_in_executor(
                    None, sqlite3.connect, str(self.db_path)
                )
                conn.row_factory = sqlite3.Row

                # Wrap in async-compatible connection
                yield AsyncConnection(conn)

            except Exception as e:
                self._failed_queries += 1
                raise DatabaseConnectionError(
                    f"Failed to connect to database: {str(e)}"
                ) from e
            finally:
                if "conn" in locals():
                    conn.close()
                self._total_queries += 1

    # Prisoner Management Methods

    async def get_or_create_prisoner(
        self, discord_id: str, username: str, display_name: Optional[str] = None
    ) -> Prisoner:
        """Get existing prisoner or create new one."""
        try:
            # Try to get existing prisoner
            prisoner = await self.get_prisoner_by_discord_id(discord_id)

            if prisoner:
                # Update last seen
                await self.update_prisoner_last_seen(prisoner.id)
                return prisoner

            # Create new prisoner
            async with self._get_connection() as conn:
                cursor = await conn.execute(
                    """
                    INSERT INTO prisoners (discord_id, username, display_name)
                    VALUES (?, ?, ?)
                    """,
                    (discord_id, username, display_name),
                )
                await conn.commit()

                prisoner_id = cursor.lastrowid

                self.logger.log_info(
                    f"New prisoner registered: {username} ({discord_id})"
                )

                return Prisoner(
                    id=prisoner_id,
                    discord_id=discord_id,
                    username=username,
                    display_name=display_name,
                    first_seen=datetime.now(),
                    last_seen=datetime.now(),
                )

        except Exception as e:
            raise DatabaseQueryError(
                f"SELECT/INSERT FROM prisoners WHERE discord_id = {discord_id}", str(e)
            ) from e

    async def get_prisoner_by_discord_id(self, discord_id: str) -> Optional[Prisoner]:
        """Get prisoner by Discord ID."""
        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT * FROM prisoners WHERE discord_id = ?", (discord_id,)
                )
                row = await cursor.fetchone()

                if row:
                    return self._row_to_prisoner(row)

                return None

        except Exception as e:
            raise DatabaseQueryError(
                "SELECT FROM prisoners WHERE discord_id = ?", str(e)
            ) from e

    async def update_prisoner_profile(
        self,
        prisoner_id: int,
        psychological_profile: Optional[str] = None,
        vulnerability_notes: Optional[str] = None,
        mute_reason: Optional[str] = None,
        mute_reason_extracted: Optional[bool] = None,
        effectiveness_score: Optional[float] = None,
        status: Optional[str] = None,
    ):
        """Update prisoner's psychological profile."""
        updates = []
        params = []

        if psychological_profile is not None:
            updates.append("psychological_profile = ?")
            params.append(psychological_profile)

        if vulnerability_notes is not None:
            updates.append("vulnerability_notes = ?")
            params.append(vulnerability_notes)

        if mute_reason is not None:
            updates.append("mute_reason = ?")
            params.append(mute_reason)

        if mute_reason_extracted is not None:
            updates.append("mute_reason_extracted = ?")
            params.append(1 if mute_reason_extracted else 0)

        if effectiveness_score is not None:
            updates.append("torture_effectiveness_score = ?")
            params.append(effectiveness_score)

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if not updates:
            return

        params.append(prisoner_id)

        try:
            async with self._get_connection() as conn:
                await conn.execute(
                    f"UPDATE prisoners SET {', '.join(updates)} WHERE id = ?",  # nosec B608
                    params,
                )
                await conn.commit()

        except Exception as e:
            raise DatabaseQueryError(
                f"UPDATE prisoners WHERE id = {prisoner_id}", str(e)
            ) from e

    async def update_prisoner_last_seen(self, prisoner_id: int):
        """Update prisoner's last seen timestamp."""
        try:
            async with self._get_connection() as conn:
                await conn.execute(
                    "UPDATE prisoners SET last_seen = CURRENT_TIMESTAMP WHERE id = ?",
                    (prisoner_id,),
                )
                await conn.commit()

        except Exception as e:
            raise DatabaseQueryError(
                "UPDATE prisoners SET last_seen WHERE id = ?", str(e)
            ) from e

    # Session Management Methods

    async def start_torture_session(
        self, prisoner_id: int, channel_id: str, channel_name: Optional[str] = None
    ) -> TortureSession:
        """Start a new torture session."""
        try:
            # Check if there's already an active session
            session_key = f"{prisoner_id}:{channel_id}"
            if session_key in self._active_sessions:
                return self._active_sessions[session_key]

            async with self._get_connection() as conn:
                cursor = await conn.execute(
                    """
                    INSERT INTO torture_sessions
                    (prisoner_id, channel_id, channel_name)
                    VALUES (?, ?, ?)
                    """,
                    (prisoner_id, channel_id, channel_name),
                )
                await conn.commit()

                session = TortureSession(
                    id=cursor.lastrowid,
                    prisoner_id=prisoner_id,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    start_time=datetime.now(),
                )

                # Cache active session
                self._active_sessions[session_key] = session

                # Update prisoner session count
                await conn.execute(
                    "UPDATE prisoners SET total_sessions = total_sessions + 1 WHERE id = ?",
                    (prisoner_id,),
                )
                await conn.commit()

                return session

        except Exception as e:
            raise DatabaseQueryError("INSERT INTO torture_sessions", str(e)) from e

    async def end_torture_session(
        self,
        session_id: int,
        confusion_level: Optional[int] = None,
        effectiveness_rating: Optional[int] = None,
        session_notes: Optional[str] = None,
    ):
        """End a torture session."""
        try:
            async with self._get_connection() as conn:
                # Get session data
                cursor = await conn.execute(
                    "SELECT * FROM torture_sessions WHERE id = ?", (session_id,)
                )
                row = await cursor.fetchone()

                if not row:
                    return

                # Update session
                updates = ["end_time = CURRENT_TIMESTAMP"]
                params = []

                if confusion_level is not None:
                    updates.append("confusion_level = ?")
                    params.append(confusion_level)

                if effectiveness_rating is not None:
                    updates.append("effectiveness_rating = ?")
                    params.append(effectiveness_rating)

                if session_notes is not None:
                    updates.append("session_notes = ?")
                    params.append(session_notes)

                # Add topics and methods as JSON
                session_key = f"{row['prisoner_id']}:{row['channel_id']}"
                if session_key in self._active_sessions:
                    session = self._active_sessions[session_key]
                    updates.append("topics_discussed = ?")
                    params.append(json.dumps(session.topics_discussed))
                    updates.append("torture_methods = ?")
                    params.append(json.dumps(session.torture_methods))

                    # Remove from active sessions
                    del self._active_sessions[session_key]

                params.append(session_id)

                await conn.execute(
                    f"UPDATE torture_sessions SET {', '.join(updates)} WHERE id = ?",  # nosec B608
                    params,
                )
                await conn.commit()

        except Exception as e:
            raise DatabaseQueryError(
                f"UPDATE torture_sessions WHERE id = {session_id}", str(e)
            ) from e

    async def get_active_session(
        self, prisoner_id: int, channel_id: str
    ) -> Optional[TortureSession]:
        """Get active session for prisoner in channel."""
        session_key = f"{prisoner_id}:{channel_id}"
        return self._active_sessions.get(session_key)

    # Conversation History Methods

    async def add_conversation_message(
        self,
        session_id: int,
        prisoner_id: int,
        message_type: str,
        content: str,
        confusion_technique: Optional[str] = None,
        emotional_state: Optional[str] = None,
    ):
        """Add a message to conversation history."""
        try:
            async with self._get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO conversation_history
                    (session_id, prisoner_id, message_type, content,
                     confusion_technique, emotional_state)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        prisoner_id,
                        message_type,
                        content,
                        confusion_technique,
                        emotional_state,
                    ),
                )
                await conn.commit()

                # Update prisoner message count if prisoner message
                if message_type == "prisoner":
                    await conn.execute(
                        "UPDATE prisoners SET total_messages = total_messages + 1 WHERE id = ?",
                        (prisoner_id,),
                    )
                    await conn.commit()

                # Update session message count
                await conn.execute(
                    "UPDATE torture_sessions SET message_count = message_count + 1 WHERE id = ?",
                    (session_id,),
                )
                await conn.commit()

        except Exception as e:
            raise DatabaseQueryError("INSERT INTO conversation_history", str(e)) from e

    async def get_prisoner_history(
        self, prisoner_id: int, limit: int = 100
    ) -> List[ConversationMessage]:
        """Get prisoner's conversation history."""
        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT * FROM conversation_history
                    WHERE prisoner_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (prisoner_id, limit),
                )
                rows = await cursor.fetchall()

                return [self._row_to_conversation_message(row) for row in rows]

        except Exception as e:
            raise DatabaseQueryError(
                "SELECT FROM conversation_history WHERE prisoner_id = ?",
                str(e),
            ) from e

    # Analytics and Reporting Methods

    async def generate_prisoner_report(self, prisoner_id: int) -> Dict[str, Any]:
        """Generate comprehensive report for a prisoner."""
        try:
            async with self._get_connection() as conn:
                # Get prisoner data
                prisoner = await self.get_prisoner_by_discord_id(str(prisoner_id))
                if not prisoner:
                    return {}

                # Get session statistics
                cursor = await conn.execute(
                    """
                    SELECT
                        COUNT(*) as total_sessions,
                        AVG(confusion_level) as avg_confusion,
                        AVG(effectiveness_rating) as avg_effectiveness,
                        SUM(message_count) as total_messages,
                        MAX(start_time) as last_session
                    FROM torture_sessions
                    WHERE prisoner_id = ?
                    """,
                    (prisoner.id,),
                )
                session_stats = dict(await cursor.fetchone())

                # Get most used confusion techniques
                cursor = await conn.execute(
                    """
                    SELECT confusion_technique, COUNT(*) as count
                    FROM conversation_history
                    WHERE prisoner_id = ? AND confusion_technique IS NOT NULL
                    GROUP BY confusion_technique
                    ORDER BY count DESC
                    LIMIT 5
                    """,
                    (prisoner.id,),
                )
                top_techniques = [
                    {"technique": row["confusion_technique"], "count": row["count"]}
                    for row in await cursor.fetchall()
                ]

                # Get emotional state distribution
                cursor = await conn.execute(
                    """
                    SELECT emotional_state, COUNT(*) as count
                    FROM conversation_history
                    WHERE prisoner_id = ? AND emotional_state IS NOT NULL
                    GROUP BY emotional_state
                    ORDER BY count DESC
                    """,
                    (prisoner.id,),
                )
                emotional_states = [
                    {"state": row["emotional_state"], "count": row["count"]}
                    for row in await cursor.fetchall()
                ]

                # Get memorable quotes
                cursor = await conn.execute(
                    """
                    SELECT prisoner_message, azab_response, effectiveness_rating
                    FROM memorable_quotes
                    WHERE prisoner_id = ?
                    ORDER BY effectiveness_rating DESC, created_at DESC
                    LIMIT 5
                    """,
                    (prisoner.id,),
                )
                memorable_quotes = [dict(row) for row in await cursor.fetchall()]

                return {
                    "prisoner": asdict(prisoner),
                    "session_statistics": session_stats,
                    "top_confusion_techniques": top_techniques,
                    "emotional_state_distribution": emotional_states,
                    "memorable_quotes": memorable_quotes,
                    "report_generated_at": datetime.now().isoformat(),
                }

        except Exception as e:
            self.logger.log_error(f"Failed to generate prisoner report: {e}")
            return {}

    async def generate_daily_report(
        self, report_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Generate daily activity report."""
        if report_date is None:
            report_date = date.today()

        try:
            async with self._get_connection() as conn:
                # Get prisoner statistics
                cursor = await conn.execute(
                    """
                    SELECT
                        COUNT(DISTINCT p.id) as total_prisoners,
                        COUNT(DISTINCT CASE WHEN DATE(p.first_seen) = ? THEN p.id END) as new_prisoners,
                        COUNT(DISTINCT CASE WHEN p.status = 'broken' THEN p.id END) as broken_prisoners,
                        COUNT(DISTINCT CASE WHEN p.status = 'resistant' THEN p.id END) as resistant_prisoners
                    FROM prisoners p
                    WHERE DATE(p.last_seen) >= ?
                    """,
                    (report_date, report_date),
                )
                prisoner_stats = dict(await cursor.fetchone())

                # Get session statistics
                cursor = await conn.execute(
                    """
                    SELECT
                        COUNT(*) as total_sessions,
                        AVG(confusion_level) as avg_confusion_level,
                        AVG(effectiveness_rating) as avg_effectiveness,
                        SUM(message_count) as total_messages
                    FROM torture_sessions
                    WHERE DATE(start_time) = ?
                    """,
                    (report_date,),
                )
                session_stats = dict(await cursor.fetchone())

                # Get most active prisoners
                cursor = await conn.execute(
                    """
                    SELECT
                        p.username,
                        p.display_name,
                        COUNT(DISTINCT ts.id) as session_count,
                        SUM(ts.message_count) as message_count
                    FROM prisoners p
                    JOIN torture_sessions ts ON p.id = ts.prisoner_id
                    WHERE DATE(ts.start_time) = ?
                    GROUP BY p.id
                    ORDER BY message_count DESC
                    LIMIT 10
                    """,
                    (report_date,),
                )
                most_active = [dict(row) for row in await cursor.fetchall()]

                # Store report in database
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO daily_reports
                    (report_date, total_prisoners, new_prisoners, total_messages,
                     total_sessions, average_confusion_level, prisoner_breakdown)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_date,
                        prisoner_stats["total_prisoners"],
                        prisoner_stats["new_prisoners"],
                        session_stats["total_messages"] or 0,
                        session_stats["total_sessions"] or 0,
                        session_stats["avg_confusion_level"] or 0,
                        json.dumps(
                            {
                                "broken": prisoner_stats["broken_prisoners"],
                                "resistant": prisoner_stats["resistant_prisoners"],
                                "active": prisoner_stats["total_prisoners"]
                                - prisoner_stats["broken_prisoners"]
                                - prisoner_stats["resistant_prisoners"],
                            }
                        ),
                    ),
                )
                await conn.commit()

                return {
                    "report_date": report_date.isoformat(),
                    "prisoner_statistics": prisoner_stats,
                    "session_statistics": session_stats,
                    "most_active_prisoners": most_active,
                    "generated_at": datetime.now().isoformat(),
                }

        except Exception as e:
            self.logger.log_error(f"Failed to generate daily report: {e}")
            return {}

    async def add_memorable_quote(
        self,
        session_id: int,
        prisoner_id: int,
        prisoner_message: str,
        azab_response: str,
        confusion_type: Optional[str] = None,
        effectiveness_rating: int = 3,
    ):
        """Add a memorable quote to the database."""
        try:
            async with self._get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO memorable_quotes
                    (session_id, prisoner_id, prisoner_message, azab_response,
                     confusion_type, effectiveness_rating)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        prisoner_id,
                        prisoner_message,
                        azab_response,
                        confusion_type,
                        effectiveness_rating,
                    ),
                )
                await conn.commit()

        except Exception as e:
            self.logger.log_error(f"Failed to add memorable quote: {e}")

    # Utility Methods

    def _row_to_prisoner(self, row: sqlite3.Row) -> Prisoner:
        """Convert database row to Prisoner object."""
        return Prisoner(
            id=row["id"],
            discord_id=row["discord_id"],
            username=row["username"],
            display_name=row["display_name"],
            total_messages=row["total_messages"],
            total_sessions=row["total_sessions"],
            psychological_profile=row["psychological_profile"],
            vulnerability_notes=row["vulnerability_notes"],
            torture_effectiveness_score=row["torture_effectiveness_score"],
            status=row["status"],
            first_seen=(
                datetime.fromisoformat(row["first_seen"]) if row["first_seen"] else None
            ),
            last_seen=(
                datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else None
            ),
        )

    def _row_to_conversation_message(self, row: sqlite3.Row) -> ConversationMessage:
        """Convert database row to ConversationMessage object."""
        return ConversationMessage(
            id=row["id"],
            session_id=row["session_id"],
            prisoner_id=row["prisoner_id"],
            message_type=row["message_type"],
            content=row["content"],
            confusion_technique=row["confusion_technique"],
            emotional_state=row["emotional_state"],
            timestamp=(
                datetime.fromisoformat(row["timestamp"]) if row["timestamp"] else None
            ),
        )

    def _calculate_success_rate(self) -> float:
        """Calculate query success rate."""
        if self._total_queries == 0:
            return 100.0
        return (
            (self._total_queries - self._failed_queries) / self._total_queries
        ) * 100


class AsyncConnection:
    """Wrapper for async database operations."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.loop = asyncio.get_event_loop()

    async def execute(self, query: str, params: Tuple = ()):
        """Execute a query asynchronously."""
        return await self.loop.run_in_executor(None, self.conn.execute, query, params)

    async def executescript(self, script: str):
        """Execute a script asynchronously."""
        return await self.loop.run_in_executor(None, self.conn.executescript, script)

    async def commit(self):
        """Commit transaction asynchronously."""
        return await self.loop.run_in_executor(None, self.conn.commit)

    async def rollback(self):
        """Rollback transaction asynchronously."""
        return await self.loop.run_in_executor(None, self.conn.rollback)
