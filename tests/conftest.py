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


# Mock Embed Field that behaves like discord.py EmbedField
class MockEmbedField:
    """Mock Discord Embed Field."""

    def __init__(self, name='', value='', inline=True):
        self.name = name
        self.value = value
        self.inline = inline


# Better Embed mock that tracks field additions
class MockEmbed:
    """Mock Discord Embed that tracks all properties."""

    def __init__(self, **kwargs):
        self.title = kwargs.get('title', '')
        self.description = kwargs.get('description', '')
        self.color = kwargs.get('color')
        self.timestamp = kwargs.get('timestamp')
        self.fields = []
        self._footer = None
        self._thumbnail = None
        self._image = None

    def add_field(self, name='', value='', inline=True):
        self.fields.append(MockEmbedField(name, value, inline))
        return self

    def set_field_at(self, index, name='', value='', inline=True):
        if 0 <= index < len(self.fields):
            self.fields[index] = MockEmbedField(name, value, inline)
        return self

    def set_footer(self, text='', icon_url=None):
        self._footer = {'text': text, 'icon_url': icon_url}
        return self

    def set_thumbnail(self, url=''):
        self._thumbnail = {'url': url}
        return self

    def set_image(self, url=''):
        self._image = {'url': url}
        return self

    def set_author(self, name='', icon_url=None, url=None):
        self._author = {'name': name, 'icon_url': icon_url, 'url': url}
        return self


# Mock View that tracks children
class MockView:
    """Mock Discord View that tracks items."""

    def __init__(self, timeout=None):
        self.timeout = timeout
        self.children = []

    def add_item(self, item):
        self.children.append(item)
        return self


# Mock Button
class MockButton:
    """Mock Discord Button."""

    def __init__(self, label='', url=None, style=None, emoji=None, custom_id=None, row=None):
        self.label = label
        self.url = url
        self.style = style
        self.emoji = emoji
        self.custom_id = custom_id
        self.row = row


# Mock PartialEmoji
class MockPartialEmoji:
    """Mock Discord PartialEmoji."""

    def __init__(self, name='', id=None):
        self.name = name
        self.id = id


# Mock DynamicItem for DownloadButton
class MockDynamicItem:
    """Mock Discord DynamicItem that can be inherited."""

    def __init__(self, *args, **kwargs):
        pass

    def __class_getitem__(cls, item):
        return cls


# Create a DynamicItem that supports class inheritance with template
class DynamicItemMeta(type):
    """Metaclass for DynamicItem that allows subscripting and template kwarg."""

    def __getitem__(cls, item):
        return cls

    def __new__(mcs, name, bases, namespace, template=None, **kwargs):
        # Accept and ignore template argument (used in discord.py for regex patterns)
        return super().__new__(mcs, name, bases, namespace)


class MockDynamicItemBase(metaclass=DynamicItemMeta):
    """Mock base class for DynamicItem."""

    def __init__(self, item=None):
        self.item = item
        self.label = getattr(item, 'label', '') if item else ''
        self.url = getattr(item, 'url', None) if item else None
        self.style = getattr(item, 'style', None) if item else None
        self.emoji = getattr(item, 'emoji', None) if item else None
        self.custom_id = getattr(item, 'custom_id', None) if item else None

    def __init_subclass__(cls, template=None, **kwargs):
        # Accept and ignore template argument
        super().__init_subclass__(**kwargs)


# Mock discord module before any imports
discord_mock = MagicMock()
discord_mock.Embed = MockEmbed
discord_mock.ForumChannel = MagicMock
discord_mock.Thread = MagicMock
discord_mock.PartialEmoji = MockPartialEmoji
discord_mock.ui = MagicMock()
discord_mock.ui.View = MockView
discord_mock.ui.Button = MockButton
discord_mock.ui.DynamicItem = MockDynamicItemBase
discord_mock.ButtonStyle = MagicMock()
discord_mock.ButtonStyle.secondary = 2
discord_mock.ButtonStyle.link = 5
discord_mock.NotFound = Exception
discord_mock.Forbidden = Exception
discord_mock.HTTPException = Exception
discord_mock.abc = MagicMock()
discord_mock.abc.GuildChannel = MagicMock
discord_mock.abc.Messageable = MagicMock
discord_mock.Message = MagicMock
sys.modules['discord'] = discord_mock
sys.modules['discord.ext'] = MagicMock()
sys.modules['discord.ext.commands'] = MagicMock()
sys.modules['discord.ui'] = discord_mock.ui
sys.modules['discord.abc'] = discord_mock.abc


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
    from datetime import datetime
    member = MagicMock()
    member.id = 123456789
    member.name = "testuser"
    member.display_name = "Test User"
    member.display_avatar.url = "https://example.com/avatar.png"
    # Use real datetime objects for timestamp comparisons
    member.created_at = datetime(2020, 9, 13, 12, 0, 0)
    member.joined_at = datetime(2022, 4, 15, 10, 0, 0)
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
