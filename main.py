#!/usr/bin/env python3
"""
Azab - Syria Discord Bot Entry Point
===================================

A custom Discord bot built specifically for discord.gg/syria.
Features modular architecture with AI-powered responses and moderation tools.

Features:
- Slash commands (/activate, /deactivate)
- AI-powered message responses
- User moderation tools
- Message logging and analytics
- Single instance enforcement
- Graceful error handling

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import sys
import fcntl
from typing import Optional
from dotenv import load_dotenv

from src.core.logger import logger
from src.bot import AzabBot
from src.utils.error_handler import ErrorHandler


def check_running_instance() -> bool:
    """
    Check if another AzabBot instance is already running system-wide.
    Uses both PID file locking and process scanning for maximum reliability.

    Returns:
        True if lock acquired successfully, False if another instance is running
    """
    import subprocess
    import signal

    pid_file = '/var/run/azabbot.pid'
    current_pid = os.getpid()

    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True,
            timeout=5
        )

        for line in result.stdout.splitlines():
            if 'python' in line and 'AzabBot' in line and 'main.py' in line:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        found_pid = int(parts[1])
                        if found_pid != current_pid:
                            try:
                                os.kill(found_pid, 0)
                                logger.error(f"❌ Another AzabBot instance is already running! (PID: {found_pid})")
                                logger.error(f"   Process: {' '.join(parts[10:])}")
                                logger.error("   Please stop the existing instance first:")
                                logger.error(f"   sudo kill {found_pid}")
                                return False
                            except OSError:
                                continue
                    except (ValueError, IndexError):
                        continue
    except Exception as e:
        logger.warning(f"Could not check running processes: {e}")

    try:
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    old_pid = int(f.read().strip())

                try:
                    os.kill(old_pid, 0)
                    logger.error(f"❌ Lock file exists with running process (PID: {old_pid})")
                    logger.error(f"   Lock file: {pid_file}")
                    return False
                except OSError:
                    logger.warning(f"Removing stale lock file (PID {old_pid} is dead)")
                    os.remove(pid_file)
            except (ValueError, IOError):
                os.remove(pid_file)

        fp = open(pid_file, 'w')
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fp.write(str(current_pid))
        fp.flush()

        logger.info(f"✅ Instance lock acquired - PID: {current_pid}, Lock file: {pid_file}")
        return True

    except IOError as e:
        logger.error(f"❌ Failed to acquire lock file: {e}")
        logger.error(f"   Lock file: {pid_file}")
        return False
    except Exception as e:
        logger.error(f"❌ Lock error: {e}")
        return False


async def main() -> None:
    """
    Main entry point for Azab Discord bot.

    Handles the complete bot lifecycle:
    1. Loads environment configuration
    2. Validates Discord bot token
    3. Initializes bot instance with proper intents
    4. Establishes connection to Discord API
    5. Handles graceful shutdown on interruption

    Raises:
        SystemExit: If bot token is missing or bot fails to start
    """
    load_dotenv()

    logger.tree("AZAB STARTING", [
        ("Server", "discord.gg/syria"),
        ("Structure", "Organized with src/"),
        ("Commands", "/activate, /deactivate")
    ], "🔥")

    token: Optional[str] = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("❌ No DISCORD_TOKEN found in .env file!")
        logger.error("   Please add your bot token to the .env file")
        sys.exit(1)

    try:
        bot: AzabBot = AzabBot()
        logger.info("🤖 Bot instance created successfully")

        await bot.start(token)

    except Exception as e:
        ErrorHandler.handle(
            e,
            location="main.main",
            critical=True,
            token_present=bool(token)
        )
        sys.exit(1)


if __name__ == "__main__":
    if not check_running_instance():
        logger.error("⛔ Startup aborted - another instance is already running")
        sys.exit(1)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        ErrorHandler.handle(
            e,
            location="main.__main__",
            critical=True
        )
        sys.exit(1)
