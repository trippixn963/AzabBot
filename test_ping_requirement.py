#!/usr/bin/env python3
"""
Test script to verify family members need to ping Azab for responses.

This ensures that dad, uncle, and brother must mention the bot
even in prison channels to get a response.
"""

import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.bot import AzabBot

async def test_family_ping_requirement():
    """Test that family members need to ping the bot."""

    print("=" * 60)
    print("TESTING FAMILY PING REQUIREMENT")
    print("=" * 60)
    print()

    # Create mock bot
    bot = AzabBot()

    # Set up IDs
    bot.developer_id = 123456789
    bot.uncle_id = 987654321
    bot.brother_id = 555555555
    bot.prison_channel_id = 111111111
    bot.allowed_channels = {111111111}
    bot.is_active = True

    # Mock the bot user
    bot.user = Mock()
    bot.user.mentioned_in = MagicMock()

    # Mock AI service
    bot.ai = Mock()
    bot.ai.generate_developer_response = AsyncMock(return_value="Test response to dad")
    bot.ai.generate_uncle_response = AsyncMock(return_value="Test response to uncle")
    bot.ai.generate_brother_response = AsyncMock(return_value="Test response to brother")

    # Mock database
    bot.db = Mock()
    bot.db.log_message = AsyncMock()

    # Test scenarios
    test_cases = [
        {
            "name": "Dad in prison channel WITHOUT ping",
            "author_id": 123456789,
            "channel_id": 111111111,
            "is_mentioned": False,
            "should_respond": False
        },
        {
            "name": "Dad in prison channel WITH ping",
            "author_id": 123456789,
            "channel_id": 111111111,
            "is_mentioned": True,
            "should_respond": True
        },
        {
            "name": "Uncle in prison channel WITHOUT ping",
            "author_id": 987654321,
            "channel_id": 111111111,
            "is_mentioned": False,
            "should_respond": False
        },
        {
            "name": "Uncle in prison channel WITH ping",
            "author_id": 987654321,
            "channel_id": 111111111,
            "is_mentioned": True,
            "should_respond": True
        },
        {
            "name": "Brother in random channel WITHOUT ping",
            "author_id": 555555555,
            "channel_id": 999999999,
            "is_mentioned": False,
            "should_respond": False
        },
        {
            "name": "Brother in random channel WITH ping",
            "author_id": 555555555,
            "channel_id": 999999999,
            "is_mentioned": True,
            "should_respond": True
        },
        {
            "name": "Regular user in prison channel WITHOUT ping",
            "author_id": 777777777,
            "channel_id": 111111111,
            "is_mentioned": False,
            "should_respond": False  # Regular users need different logic
        }
    ]

    for test_case in test_cases:
        print(f"Testing: {test_case['name']}")

        # Create mock message
        message = Mock()
        message.author = Mock()
        message.author.id = test_case["author_id"]
        message.author.bot = False
        message.author.display_name = "TestUser"
        message.channel = Mock()
        message.channel.id = test_case["channel_id"]
        message.channel.typing = AsyncMock()
        message.content = "Test message"
        message.reply = AsyncMock()
        message.embeds = []
        message.guild = Mock()
        message.guild.id = 12345

        # Set up mentioned_in return value
        bot.user.mentioned_in.return_value = test_case["is_mentioned"]

        # Mock is_user_muted
        bot.is_user_muted = MagicMock(return_value=False)

        # Process message
        await bot.on_message(message)

        # Check if response was sent
        if test_case["should_respond"]:
            assert message.reply.called, f"❌ Bot should have responded but didn't"
            print(f"  ✅ Bot responded as expected")
        else:
            assert not message.reply.called, f"❌ Bot responded when it shouldn't have"
            print(f"  ✅ Bot correctly did not respond")

        # Reset mock
        message.reply.reset_mock()
        print()

    print("=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("Family members now need to ping the bot to get responses.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_family_ping_requirement())