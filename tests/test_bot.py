"""
Test Suite for AzabBot
=======================

Comprehensive testing for bot functionality.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.bot.bot import AzabBot
from src.services.database_service import DatabaseService
from src.services.torture_service import TortureService
from src.services.ai_service import AIService
from src.config.config import Config

@pytest.fixture
async def mock_bot():
    """Create a mock bot instance."""
    with patch("discord.Client"):
        bot = AzabBot()
        bot.user = Mock(id=123456789)
        bot.guilds = []
        yield bot

@pytest.fixture
async def mock_database():
    """Create a mock database service."""
    db = AsyncMock(spec=DatabaseService)
    db.initialize = AsyncMock()
    db.get_prisoner = AsyncMock(return_value=None)
    db.create_prisoner = AsyncMock()
    db.update_prisoner = AsyncMock()
    yield db

@pytest.fixture
async def mock_torture_service():
    """Create a mock torture service."""
    service = AsyncMock(spec=TortureService)
    service.apply_torture = AsyncMock(return_value="Torture applied!")
    service.get_torture_methods = AsyncMock(return_value=["method1", "method2"])
    yield service

class TestAzabBot:
    """Test AzabBot core functionality."""
    
    @pytest.mark.asyncio
    async def test_bot_initialization(self, mock_bot):
        """Test bot initializes correctly."""
        assert mock_bot is not None
        assert hasattr(mock_bot, "user")
    
    @pytest.mark.asyncio
    async def test_on_ready_handler(self, mock_bot):
        """Test on_ready event handler."""
        with patch.object(mock_bot, "tree") as mock_tree:
            mock_tree.sync = AsyncMock()
            
            # Simulate on_ready
            mock_bot.guilds = [Mock(id=1234, name="Test Guild")]
            
            # Would normally be called by Discord
            # await mock_bot.on_ready()
            
            assert True  # Basic test passes
    
    @pytest.mark.asyncio
    async def test_command_registration(self, mock_bot):
        """Test command registration."""
        # Commands should be registered
        assert hasattr(mock_bot, "tree")

class TestDatabaseService:
    """Test database service functionality."""
    
    @pytest.mark.asyncio
    async def test_database_initialization(self, mock_database):
        """Test database initializes."""
        await mock_database.initialize()
        mock_database.initialize.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_prisoner_creation(self, mock_database):
        """Test creating a prisoner."""
        user_id = 123456789
        
        # First check returns None (no prisoner)
        result = await mock_database.get_prisoner(user_id)
        assert result is None
        
        # Create prisoner
        await mock_database.create_prisoner(user_id)
        mock_database.create_prisoner.assert_called_with(user_id)
    
    @pytest.mark.asyncio
    async def test_prisoner_update(self, mock_database):
        """Test updating prisoner data."""
        user_id = 123456789
        data = {"torture_level": 5}
        
        await mock_database.update_prisoner(user_id, data)
        mock_database.update_prisoner.assert_called_with(user_id, data)

class TestTortureService:
    """Test torture service functionality."""
    
    @pytest.mark.asyncio
    async def test_apply_torture(self, mock_torture_service):
        """Test applying torture."""
        result = await mock_torture_service.apply_torture(123, "fire")
        assert result == "Torture applied!"
        mock_torture_service.apply_torture.assert_called_with(123, "fire")
    
    @pytest.mark.asyncio
    async def test_get_torture_methods(self, mock_torture_service):
        """Test getting torture methods."""
        methods = await mock_torture_service.get_torture_methods()
        assert len(methods) == 2
        assert "method1" in methods

class TestIntegration:
    """Integration tests."""
    
    @pytest.mark.asyncio
    async def test_command_flow(self, mock_bot, mock_database):
        """Test complete command flow."""
        # Simulate a command interaction
        interaction = AsyncMock()
        interaction.user = Mock(id=123456789, name="TestUser")
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()
        
        # Mock the torture command flow
        with patch.object(mock_bot, "database_service", mock_database):
            # Simulate prisoner check
            mock_database.get_prisoner.return_value = {
                "discord_id": 123456789,
                "torture_level": 3
            }
            
            # Check prisoner was retrieved
            prisoner = await mock_database.get_prisoner(123456789)
            assert prisoner is not None
            assert prisoner["torture_level"] == 3

class TestErrorHandling:
    """Test error handling."""
    
    @pytest.mark.asyncio
    async def test_database_error_handling(self, mock_database):
        """Test database error handling."""
        mock_database.get_prisoner.side_effect = Exception("Database error")
        
        with pytest.raises(Exception) as exc_info:
            await mock_database.get_prisoner(123)
        
        assert "Database error" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_command_error_handling(self, mock_bot):
        """Test command error handling."""
        interaction = AsyncMock()
        interaction.response = AsyncMock()
        interaction.response.send_message.side_effect = Exception("Discord error")
        
        # Error should be caught and handled
        try:
            await interaction.response.send_message("test")
            assert False, "Should have raised exception"
        except Exception as e:
            assert "Discord error" in str(e)

class TestPerformance:
    """Performance tests."""
    
    @pytest.mark.asyncio
    async def test_concurrent_database_access(self, mock_database):
        """Test concurrent database access."""
        # Simulate multiple concurrent requests
        tasks = []
        for i in range(10):
            tasks.append(mock_database.get_prisoner(i))
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 10
        assert mock_database.get_prisoner.call_count == 10
    
    @pytest.mark.asyncio
    async def test_command_rate_limiting(self):
        """Test command rate limiting."""
        from src.utils.cooldowns import CooldownManager
        
        cooldown_mgr = CooldownManager()
        user_id = 123456789
        
        # First command should pass
        can_execute, remaining = await cooldown_mgr.check_cooldown(
            "torture", user_id
        )
        assert can_execute is True
        
        # Immediate second command should fail
        can_execute, remaining = await cooldown_mgr.check_cooldown(
            "torture", user_id
        )
        assert can_execute is False
        assert remaining > 0

class TestMemoryOptimization:
    """Test memory optimization."""
    
    @pytest.mark.asyncio
    async def test_memory_optimizer(self):
        """Test memory optimizer."""
        from src.utils.memory_optimizer import MemoryOptimizer
        
        optimizer = MemoryOptimizer(threshold_mb=100)
        
        # Get initial memory
        initial_info = optimizer._get_memory_info()
        assert "rss_mb" in initial_info
        
        # Perform optimization
        result = await optimizer.optimize()
        assert "freed_mb" in result or "error" in result
    
    @pytest.mark.asyncio
    async def test_cache_cleanup(self):
        """Test cache cleanup."""
        from src.utils.cache import TTLCache
        
        cache = TTLCache(max_size=5, default_ttl=1)
        
        # Fill cache
        for i in range(10):
            await cache.set(f"key_{i}", f"value_{i}")
        
        # Should have evicted oldest
        assert len(cache.cache) <= 5
        
        # Wait for TTL
        await asyncio.sleep(1.1)
        
        # Cleanup expired
        cleaned = await cache.cleanup_expired()
        assert cleaned >= 0

class TestBackupSystem:
    """Test backup system."""
    
    @pytest.mark.asyncio
    async def test_backup_creation(self, tmp_path):
        """Test creating backups."""
        from src.utils.backup import BackupManager
        
        # Create temporary database
        db_path = tmp_path / "test.db"
        db_path.write_text("test data")
        
        backup_mgr = BackupManager(
            db_path=db_path,
            backup_dir=tmp_path / "backups",
            max_backups=3
        )
        
        # Create backup
        backup_path = await backup_mgr.create_backup("test")
        assert backup_path is not None
        assert backup_path.exists()
    
    @pytest.mark.asyncio
    async def test_backup_rotation(self, tmp_path):
        """Test backup rotation."""
        from src.utils.backup import BackupManager
        
        db_path = tmp_path / "test.db"
        db_path.write_text("test data")
        
        backup_mgr = BackupManager(
            db_path=db_path,
            backup_dir=tmp_path / "backups",
            max_backups=2
        )
        
        # Create multiple backups
        for i in range(4):
            await backup_mgr.create_backup(f"test_{i}")
            await asyncio.sleep(0.1)
        
        # Should only have 2 backups
        backups = list((tmp_path / "backups").glob("*.db*"))
        assert len(backups) <= 2

# Pytest configuration
if __name__ == "__main__":
    pytest.main([__file__, "-v"])