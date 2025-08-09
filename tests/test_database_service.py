"""Tests for database service module."""

import pytest
import asyncio
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path

from src.services.database_service import (
    DatabaseService,
    PrisonerRecord,
    TortureSession,
    ConversationEntry
)
from src.core.exceptions import (
    DatabaseConnectionError,
    DatabaseQueryError,
    ServiceError
)


@pytest.fixture
async def db_service():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"
        service = DatabaseService(str(db_path))
        await service.start()
        yield service
        await service.stop()


@pytest.fixture
async def populated_db(db_service):
    """Create a database with test data."""
    # Add test prisoner
    prisoner = await db_service.create_prisoner(
        discord_id=123456789,
        username="TestPrisoner",
        guild_id=987654321,
        channel_id=111222333
    )
    
    # Add torture session
    session = await db_service.start_torture_session(
        prisoner_id=prisoner.id,
        reason="Testing",
        duration="1 hour"
    )
    
    # Add conversation
    await db_service.add_conversation_entry(
        prisoner_id=prisoner.id,
        session_id=session.id,
        message_type="prisoner",
        content="Why am I here?"
    )
    
    return db_service, prisoner, session


class TestDatabaseService:
    """Test cases for DatabaseService class."""

    @pytest.mark.asyncio
    async def test_service_initialization(self, db_service):
        """Test database service initialization."""
        assert db_service.is_healthy()
        
        # Check tables exist
        async with db_service._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = await cursor.fetchall()
            table_names = [t[0] for t in tables]
            
            assert "prisoners" in table_names
            assert "torture_sessions" in table_names
            assert "conversation_history" in table_names

    @pytest.mark.asyncio
    async def test_create_prisoner(self, db_service):
        """Test prisoner creation."""
        prisoner = await db_service.create_prisoner(
            discord_id=111111111,
            username="NewPrisoner",
            guild_id=222222222,
            channel_id=333333333
        )
        
        assert prisoner.id > 0
        assert prisoner.discord_id == 111111111
        assert prisoner.username == "NewPrisoner"
        assert prisoner.status == "active"
        assert prisoner.total_sessions == 0

    @pytest.mark.asyncio
    async def test_get_prisoner_by_discord_id(self, populated_db):
        """Test retrieving prisoner by Discord ID."""
        db_service, original_prisoner, _ = populated_db
        
        prisoner = await db_service.get_prisoner_by_discord_id(123456789)
        
        assert prisoner is not None
        assert prisoner.id == original_prisoner.id
        assert prisoner.username == "TestPrisoner"

    @pytest.mark.asyncio
    async def test_get_nonexistent_prisoner(self, db_service):
        """Test retrieving non-existent prisoner."""
        prisoner = await db_service.get_prisoner_by_discord_id(999999999)
        assert prisoner is None

    @pytest.mark.asyncio
    async def test_update_prisoner_profile(self, populated_db):
        """Test updating prisoner profile."""
        db_service, prisoner, _ = populated_db
        
        await db_service.update_prisoner_profile(
            prisoner_id=prisoner.id,
            psychological_profile="Anxious and confused",
            personality_traits=["anxious", "defensive"],
            total_sessions=5
        )
        
        updated = await db_service.get_prisoner_by_discord_id(prisoner.discord_id)
        
        assert updated.psychological_profile == "Anxious and confused"
        assert updated.personality_traits == "anxious,defensive"
        assert updated.total_sessions == 5

    @pytest.mark.asyncio
    async def test_start_torture_session(self, populated_db):
        """Test starting a torture session."""
        db_service, prisoner, _ = populated_db
        
        session = await db_service.start_torture_session(
            prisoner_id=prisoner.id,
            reason="Test reason",
            duration="2 hours"
        )
        
        assert session.id > 0
        assert session.prisoner_id == prisoner.id
        assert session.reason == "Test reason"
        assert session.status == "active"
        assert session.message_count == 0

    @pytest.mark.asyncio
    async def test_end_torture_session(self, populated_db):
        """Test ending a torture session."""
        db_service, prisoner, session = populated_db
        
        await db_service.end_torture_session(
            session_id=session.id,
            end_reason="Time expired"
        )
        
        # Get updated session
        async with db_service._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT status, end_reason FROM torture_sessions WHERE id = ?",
                (session.id,)
            )
            row = await cursor.fetchone()
        
        assert row[0] == "completed"
        assert row[1] == "Time expired"

    @pytest.mark.asyncio
    async def test_get_active_session(self, populated_db):
        """Test retrieving active session."""
        db_service, prisoner, session = populated_db
        
        active_session = await db_service.get_active_session(prisoner.id)
        
        assert active_session is not None
        assert active_session.id == session.id
        assert active_session.status == "active"

    @pytest.mark.asyncio
    async def test_add_conversation_entry(self, populated_db):
        """Test adding conversation entries."""
        db_service, prisoner, session = populated_db
        
        entry = await db_service.add_conversation_entry(
            prisoner_id=prisoner.id,
            session_id=session.id,
            message_type="azab",
            content="Tell me what happened."
        )
        
        assert entry.id > 0
        assert entry.message_type == "azab"
        assert entry.content == "Tell me what happened."

    @pytest.mark.asyncio
    async def test_get_conversation_history(self, populated_db):
        """Test retrieving conversation history."""
        db_service, prisoner, session = populated_db
        
        # Add more messages
        await db_service.add_conversation_entry(
            prisoner_id=prisoner.id,
            session_id=session.id,
            message_type="azab",
            content="I'm here to help."
        )
        
        history = await db_service.get_conversation_history(
            prisoner_id=prisoner.id,
            limit=10
        )
        
        assert len(history) == 2
        assert history[0].message_type == "prisoner"
        assert history[1].message_type == "azab"

    @pytest.mark.asyncio
    async def test_get_prisoner_statistics(self, populated_db):
        """Test retrieving prisoner statistics."""
        db_service, prisoner, session = populated_db
        
        # Add more data
        await db_service.add_conversation_entry(
            prisoner_id=prisoner.id,
            session_id=session.id,
            message_type="azab",
            content="Message 1"
        )
        await db_service.add_conversation_entry(
            prisoner_id=prisoner.id,
            session_id=session.id,
            message_type="prisoner",
            content="Message 2"
        )
        
        stats = await db_service.get_prisoner_statistics(prisoner.id)
        
        assert stats["total_sessions"] == 1
        assert stats["total_messages"] == 3
        assert stats["active_session"] is not None
        assert "first_imprisonment" in stats
        assert "last_seen" in stats

    @pytest.mark.asyncio
    async def test_search_prisoners(self, db_service):
        """Test searching prisoners."""
        # Create multiple prisoners
        await db_service.create_prisoner(111, "Alice", 999, 888)
        await db_service.create_prisoner(222, "Bob", 999, 888)
        await db_service.create_prisoner(333, "Charlie", 999, 888)
        
        # Search by username
        results = await db_service.search_prisoners(username_pattern="li")
        assert len(results) == 2  # Alice and Charlie
        
        # Search by guild
        results = await db_service.search_prisoners(guild_id=999)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_cleanup_old_conversations(self, db_service):
        """Test cleanup of old conversations."""
        # Create prisoner and session
        prisoner = await db_service.create_prisoner(555, "OldTimer", 666, 777)
        session = await db_service.start_torture_session(
            prisoner.id, "Old reason", "1 hour"
        )
        
        # Add old conversation
        async with db_service._get_connection() as conn:
            old_time = (datetime.utcnow() - timedelta(days=40)).isoformat()
            await conn.execute(
                """INSERT INTO conversation_history 
                   (prisoner_id, session_id, message_type, content, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (prisoner.id, session.id, "azab", "Old message", old_time)
            )
            await conn.commit()
        
        # Add recent conversation
        await db_service.add_conversation_entry(
            prisoner.id, session.id, "azab", "Recent message"
        )
        
        # Cleanup old conversations
        deleted = await db_service.cleanup_old_conversations(days=30)
        assert deleted == 1
        
        # Check only recent message remains
        history = await db_service.get_conversation_history(prisoner.id)
        assert len(history) == 1
        assert history[0].content == "Recent message"

    @pytest.mark.asyncio
    async def test_database_metrics(self, populated_db):
        """Test database metrics collection."""
        db_service, _, _ = populated_db
        
        metrics = await db_service.get_database_metrics()
        
        assert metrics["total_prisoners"] >= 1
        assert metrics["active_sessions"] >= 1
        assert metrics["total_conversations"] >= 1
        assert "database_size" in metrics
        assert metrics["database_size"] > 0

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, db_service):
        """Test concurrent database operations."""
        # Create multiple prisoners concurrently
        tasks = [
            db_service.create_prisoner(
                discord_id=1000 + i,
                username=f"User{i}",
                guild_id=9999,
                channel_id=8888
            )
            for i in range(10)
        ]
        
        prisoners = await asyncio.gather(*tasks)
        
        assert len(prisoners) == 10
        assert all(p.id > 0 for p in prisoners)
        
        # Verify all were created
        results = await db_service.search_prisoners(guild_id=9999)
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, db_service):
        """Test transaction rollback on error."""
        # This should fail due to duplicate discord_id
        await db_service.create_prisoner(12345, "First", 111, 222)
        
        with pytest.raises(DatabaseQueryError):
            await db_service.create_prisoner(12345, "Duplicate", 111, 222)
        
        # Verify only one prisoner exists
        prisoner = await db_service.get_prisoner_by_discord_id(12345)
        assert prisoner.username == "First"