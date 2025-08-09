"""Basic tests for SaydnayaBot."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from src.bot.bot import SaydnayaBot


class TestSaydnayaBot:
    """Test cases for the main bot class."""

    def test_bot_initialization(self):
        """Test bot can be initialized with config."""
        config = {
            "developer_id": 123456789,
            "response_probability": 0.7,
            "prison_mode": False,
        }
        bot = SaydnayaBot(config)
        assert bot.developer_id == 123456789
        assert bot.response_probability == 0.7
        assert bot.is_active is False

    def test_bot_requires_developer_id(self):
        """Test bot raises error without developer_id."""
        config = {}
        with pytest.raises(ValueError, match="DEVELOPER_ID must be set"):
            SaydnayaBot(config)

    def test_is_prison_channel(self):
        """Test prison channel detection."""
        config = {"developer_id": 123456789, "prison_channel_ids": ["999"]}
        bot = SaydnayaBot(config)
        
        # Test keyword detection
        assert bot._is_prison_channel("timeout-corner", 123) is True
        assert bot._is_prison_channel("general-chat", 123) is False
        
        # Test explicit ID
        assert bot._is_prison_channel("any-name", 999) is True