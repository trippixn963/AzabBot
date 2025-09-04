#!/usr/bin/env python3
"""
Azab - Syria Discord Bot Entry Point
===================================

A custom Discord bot built specifically for discord.gg/syria
Features modular architecture with AI-powered responses and moderation tools.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: Modular

Discord Bot Features:
- Slash commands (/activate, /deactivate)
- AI-powered message responses
- User moderation tools
- Message logging and analytics
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

from src.core.logger import logger
from src.utils.version import Version
from src.bot import AzabBot


async def main() -> None:
    """
    Main entry point for Azab Discord bot.
    
    This function handles the complete bot lifecycle:
    1. Loads environment configuration
    2. Validates Discord bot token
    3. Initializes bot instance with proper intents
    4. Establishes connection to Discord API
    5. Handles graceful shutdown on interruption
    
    Raises:
        SystemExit: If bot token is missing or bot fails to start
    """
    # Load environment variables from .env file
    # Required: DISCORD_TOKEN, OPENAI_API_KEY
    load_dotenv()
    
    # Display startup information with version
    version_info = Version.get_full_info()
    version_info["release_type"] = Version.get_release_type()
    logger.bot_start(version_info)
    
    # Validate Discord bot token from environment
    # Bot token is required for Discord API authentication
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("Configuration", "No DISCORD_TOKEN found in .env file")
        sys.exit(1)
    
    # Initialize bot instance and connect to Discord
    # AzabBot handles all Discord events and command interactions
    try:
        bot = AzabBot()
        logger.service_status("Bot Instance", "created")
        
        # Start the bot and connect to Discord Gateway
        # This will trigger on_ready event when connection is established
        await bot.start(token)
        
    except Exception as e:
        logger.error("Bot Startup", str(e))
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.service_status("Bot", "stopped by user")
    except Exception as e:
        logger.error("Unexpected", str(e))
        sys.exit(1)