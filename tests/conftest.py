"""
Azab Discord Bot - Test Fixtures
=================================

Shared fixtures for all tests.
"""

import os
import sys
import sqlite3
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set up test environment before importing modules
os.environ["TESTING"] = "1"

# Mock openai module before any imports
openai_mock = MagicMock()
openai_mock.AsyncOpenAI = MagicMock
sys.modules['openai'] = openai_mock

# Mock aiohttp
aiohttp_mock = MagicMock()
sys.modules['aiohttp'] = aiohttp_mock

# Mock psutil
psutil_mock = MagicMock()
sys.modules['psutil'] = psutil_mock

# Create a subscriptable mock class for generic types
class SubscriptableMock(MagicMock):
    def __getitem__(self, item):
        return self

# Mock discord module before any imports
discord_mock = MagicMock()
discord_mock.Embed = MagicMock()
discord_mock.Embed.return_value = MagicMock(fields=[], title="", color=None)
discord_mock.ForumChannel = MagicMock
discord_mock.Thread = MagicMock
discord_mock.ui = MagicMock()
discord_mock.ui.View = SubscriptableMock()
discord_mock.ui.Button = SubscriptableMock()
discord_mock.ui.DynamicItem = SubscriptableMock()
discord_mock.ButtonStyle = MagicMock()
discord_mock.ButtonStyle.secondary = 2
discord_mock.ButtonStyle.link = 5
discord_mock.NotFound = Exception
discord_mock.Forbidden = Exception
discord_mock.HTTPException = Exception
sys.modules['discord'] = discord_mock
sys.modules['discord.ext'] = MagicMock()
sys.modules['discord.ext.commands'] = MagicMock()
sys.modules['discord.ui'] = discord_mock.ui


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database path for testing."""
    return tmp_path / "test_azab.db"


@pytest.fixture
def test_db(temp_db_path, monkeypatch):
    """Create a fresh test database instance."""
    # We need to reset the singleton and patch the DB path
    from src.core import database as db_module

    # Reset singleton
    db_module.DatabaseManager._instance = None

    # Patch the DB path
    monkeypatch.setattr(db_module, "DB_PATH", temp_db_path)
    monkeypatch.setattr(db_module, "DATA_DIR", temp_db_path.parent)

    # Create new instance
    db = db_module.DatabaseManager()

    yield db

    # Cleanup
    db.close()
    db_module.DatabaseManager._instance = None


@pytest.fixture
def mock_discord_member():
    """Create a mock Discord member."""
    member = MagicMock()
    member.id = 123456789
    member.name = "testuser"
    member.display_name = "Test User"
    member.display_avatar.url = "https://example.com/avatar.png"
    member.created_at = MagicMock()
    member.created_at.timestamp.return_value = 1600000000
    member.joined_at = MagicMock()
    member.joined_at.timestamp.return_value = 1650000000
    member.guild = MagicMock()
    member.guild.id = 987654321
    member.roles = []
    member.mention = "<@123456789>"
    return member


@pytest.fixture
def mock_discord_moderator():
    """Create a mock Discord moderator."""
    mod = MagicMock()
    mod.id = 111222333
    mod.name = "moduser"
    mod.display_name = "Mod User"
    mod.display_avatar.url = "https://example.com/mod_avatar.png"
    mod.guild = MagicMock()
    mod.guild.id = 987654321
    mod.mention = "<@111222333>"
    return mod


@pytest.fixture
def mock_discord_thread():
    """Create a mock Discord thread."""
    thread = MagicMock()
    thread.id = 555666777
    thread.name = "[ABCD] | Test User"
    thread.guild = MagicMock()
    thread.guild.id = 987654321
    thread.send = AsyncMock(return_value=MagicMock(id=888999000))
    thread.pins = AsyncMock(return_value=[])
    thread.fetch_message = AsyncMock()
    return thread


@pytest.fixture
def mock_discord_forum():
    """Create a mock Discord forum channel."""
    forum = MagicMock()
    forum.id = 444555666
    forum.name = "case-logs"
    forum.create_thread = AsyncMock()
    return forum


@pytest.fixture
def mock_bot(mock_discord_forum):
    """Create a mock bot instance."""
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.fetch_channel = AsyncMock(return_value=mock_discord_forum)
    bot.wait_until_ready = AsyncMock()
    return bot
