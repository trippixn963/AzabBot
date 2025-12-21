#!/usr/bin/env python3
"""
Azab Discord Bot - Main Entry Point
====================================

Application entry point with single-instance enforcement and graceful startup.

This module handles:
- Single-instance lock acquisition (prevents duplicate bots)
- Environment configuration loading
- Graceful error handling and logging
- Bot initialization and execution

Usage:
    python main.py

    Or with a process manager:
    nohup python main.py > /dev/null 2>&1 &

Environment Variables:
    DISCORD_TOKEN: Required. Discord bot authentication token.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import sys
import fcntl
import signal
import asyncio
import tempfile
from pathlib import Path
from typing import NoReturn, Optional

# CRITICAL: Load environment variables BEFORE importing any local modules
# that read from environment at import time (e.g., config.py)
from dotenv import load_dotenv
load_dotenv()

from src.core.logger import logger
from src.core.config import get_config, ConfigValidationError


# =============================================================================
# Global State for Signal Handling
# =============================================================================

_bot_instance = None
_shutdown_event: Optional[asyncio.Event] = None


# =============================================================================
# Constants
# =============================================================================

LOCK_FILE_PATH = Path(tempfile.gettempdir()) / "azab_bot.lock"
"""Path to the lock file used for single-instance enforcement."""


# =============================================================================
# Single Instance Lock
# =============================================================================

def acquire_lock() -> int:
    """
    Acquire an exclusive file lock to ensure only one bot instance runs.

    Uses fcntl.flock() for atomic lock acquisition. The lock is automatically
    released when the process terminates (even on crash), preventing stale locks.

    Returns:
        File descriptor of the lock file (kept open for lock lifetime).

    Raises:
        SystemExit: If another instance is already running.

    Example:
        >>> lock_fd = acquire_lock()
        >>> # Bot runs with lock held
        >>> # Lock automatically released on exit
    """
    try:
        # Create or open lock file
        fd = os.open(str(LOCK_FILE_PATH), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        logger.error("Failed to Open Lock File", [
            ("Path", str(LOCK_FILE_PATH)),
            ("Error", str(e)),
        ])
        sys.exit(1)

    try:
        # Attempt non-blocking exclusive lock
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Lock acquired - write our PID
        os.truncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())

        logger.info("Lock Acquired Successfully", [
            ("PID", str(os.getpid())),
        ])
        return fd

    except (IOError, OSError):
        # Lock held by another process - check if it's stale
        if _is_stale_lock(fd):
            # Stale lock - try to clean up and acquire
            os.close(fd)
            try:
                LOCK_FILE_PATH.unlink()
                logger.warning("Removed Stale Lock File", [
                    ("Reason", "Dead process"),
                ])
                return acquire_lock()  # Retry
            except OSError:
                pass

        _report_existing_instance(fd)
        os.close(fd)
        sys.exit(1)


def _is_stale_lock(fd: int) -> bool:
    """
    Check if the lock is stale (process no longer running).

    Args:
        fd: File descriptor of the lock file.

    Returns:
        True if the PID in the lock file is not running.
    """
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        pid_str = os.read(fd, 100).decode().strip()

        if not pid_str:
            return False

        pid = int(pid_str)

        # Check if process exists (signal 0 doesn't kill, just checks)
        os.kill(pid, 0)
        return False  # Process exists

    except (OSError, ValueError):
        # Process doesn't exist or invalid PID
        return True


def _report_existing_instance(fd: int) -> None:
    """
    Log information about the existing bot instance holding the lock.

    Args:
        fd: File descriptor of the lock file.
    """
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        existing_pid = os.read(fd, 100).decode().strip()

        if existing_pid:
            logger.error("Another Instance Already Running", [
                ("Existing PID", existing_pid),
                ("Kill Command", f"kill {existing_pid}"),
            ])
        else:
            logger.error("Another Instance Already Running", [
                ("PID", "Unknown"),
            ])

    except (OSError, ValueError) as e:
        logger.error("Another Instance Already Running", [
            ("PID", "Could not read"),
            ("Error", str(e)),
        ])


# =============================================================================
# Configuration
# =============================================================================

def load_configuration() -> str:
    """
    Load and validate environment configuration.

    Loads variables from .env file and validates required settings.

    Returns:
        Discord bot token.

    Raises:
        SystemExit: If required configuration is missing.
    """
    try:
        config = get_config()
        return config.discord_token
    except ConfigValidationError as e:
        logger.error("Configuration Validation Failed", [
            ("Error", str(e)),
            ("Action", "Check your .env file"),
        ])
        sys.exit(1)


# =============================================================================
# Signal Handlers
# =============================================================================

def _create_signal_handler(signum: int) -> None:
    """
    Create a thread-safe signal handler for the given signal.

    This is called from the event loop via loop.add_signal_handler(),
    ensuring thread-safety when accessing asyncio primitives.

    Args:
        signum: Signal number received
    """
    global _bot_instance

    signal_name = signal.Signals(signum).name
    logger.info("Signal Received", [
        ("Signal", signal_name),
        ("Action", "Initiating graceful shutdown"),
    ])

    if _bot_instance:
        # Safe to create task since we're called from the event loop
        asyncio.create_task(_bot_instance.close())


def _setup_signal_handlers_sync() -> None:
    """
    Setup synchronous signal handlers (fallback for non-async context).

    Used during startup before the event loop is running.
    """
    def handle_signal(signum: int, frame) -> None:
        signal_name = signal.Signals(signum).name
        logger.info("Signal Received (Pre-Loop)", [
            ("Signal", signal_name),
            ("Action", "Initiating shutdown"),
        ])
        sys.exit(0)

    # Only setup on Unix-like systems
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, handle_signal)

    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, handle_signal)


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> NoReturn:
    """
    Main entry point for the Azab Discord bot.

    Execution flow:
    1. Acquire single-instance lock
    2. Load environment configuration
    3. Initialize and start bot
    4. Handle shutdown gracefully

    Raises:
        SystemExit: On startup failure or clean shutdown.
    """
    # Step 1: Ensure single instance
    lock_fd = acquire_lock()

    # Step 2: Load configuration
    token = load_configuration()

    # Step 3: Setup synchronous signal handlers (for pre-loop phase)
    _setup_signal_handlers_sync()

    # Step 4: Initialize and run bot
    global _bot_instance
    try:
        logger.tree("AZAB STARTING", [
            ("Purpose", "Prison Warden Bot"),
            ("Features", "AI roasts, prisoner tracking, family system"),
            ("Server", "discord.gg/syria"),
            ("Lock File", str(LOCK_FILE_PATH)),
            ("PID", str(os.getpid())),
        ], emoji="🔥")

        from src.bot import AzabBot
        bot = AzabBot()
        _bot_instance = bot  # Store for signal handler access
        bot.run(token)

    except KeyboardInterrupt:
        logger.info("Shutdown Requested", [
            ("By", "User (Ctrl+C)"),
        ])
        sys.exit(0)

    except Exception as e:
        logger.error("Fatal Error During Bot Execution", [
            ("Error", str(e)),
        ])
        sys.exit(1)

    finally:
        # Explicitly close lock file descriptor for clarity
        if 'lock_fd' in locals():
            try:
                os.close(lock_fd)
            except OSError:
                pass
        logger.info("Bot Shutdown Complete")


# =============================================================================
# Script Execution
# =============================================================================

if __name__ == "__main__":
    main()
