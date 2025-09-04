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
    
    # Display startup information for debugging
    logger.tree("AZAB STARTING", [
        ("Version", "Modular"),
        ("Server", "discord.gg/syria"),
        ("Structure", "Organized with src/"),
        ("Commands", "/activate and /deactivate only")
    ], "🔥")
    
    # Validate Discord bot token from environment
    # Bot token is required for Discord API authentication
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("❌ No DISCORD_TOKEN found in .env file!")
        logger.error("   Please add your bot token to the .env file")
        sys.exit(1)
    
    # Initialize bot instance and connect to Discord
    # AzabBot handles all Discord events and command interactions
    try:
        bot = AzabBot()
        logger.info("🤖 Bot instance created successfully")
        
        # Start the bot and connect to Discord Gateway
        # This will trigger on_ready event when connection is established
        await bot.start(token)
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        sys.exit(1)