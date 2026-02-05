#!/usr/bin/env python3
"""
Azab Discord Bot - Main Entry Point
====================================

Application entry point with single-instance lock and graceful startup.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import fcntl
import os
import platform
import signal
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# CRITICAL: Load environment variables BEFORE importing any local modules
# that read from environment at import time (e.g., config.py)
from dotenv import load_dotenv
load_dotenv()

import discord
from src.core.logger import logger
from src.core.config import ConfigValidationError, validate_and_log_config
from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

LOCK_FILE_PATH = Path(tempfile.gettempdir()) / "azab_bot.lock"
"""Path to the lock file used for single-instance enforcement."""

FILE_PERMISSION_RW = 0o644
"""File permission for lock file (owner read/write, others read)."""

BOT_NAME = "Azab"
"""Bot display name for logging."""

RUN_ID = str(uuid.uuid4())[:8]
"""Unique identifier for this bot run (first 8 chars of UUID)."""


def _get_start_time() -> str:
    """Get formatted start time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_git_commit() -> str:
    """Get current git commit hash (short)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


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
    """
    try:
        fd = os.open(str(LOCK_FILE_PATH), os.O_RDWR | os.O_CREAT, FILE_PERMISSION_RW)
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

        logger.info("🔒 Lock Acquired Successfully", [
            ("PID", str(os.getpid())),
            ("Lock File", str(LOCK_FILE_PATH)),
        ])
        return fd

    except (IOError, OSError):
        # Lock held by another process - check if it's stale
        if _is_stale_lock(fd):
            # Stale lock - the PID in the file is dead but flock is still held
            # This can happen if the file was manually created or corrupted
            # Close our fd and try to forcefully take the lock
            os.close(fd)
            try:
                # Remove the stale lock file
                LOCK_FILE_PATH.unlink()
                logger.warning("🔒 Removed Stale Lock File", [
                    ("Reason", "Dead process"),
                ])
                # Small delay to avoid race with other potential starters
                import time
                time.sleep(0.1)
                return acquire_lock()  # Retry
            except OSError as e:
                logger.debug("Could Not Remove Stale Lock", [
                    ("Error", str(e)),
                    ("Action", "Proceeding to check existing instance"),
                ])
                # Another process may have already taken the lock
                sys.exit(1)

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
            logger.error("🔒 Another Instance Already Running", [
                ("Existing PID", existing_pid),
                ("Kill Command", f"kill {existing_pid}"),
            ])
        else:
            logger.error("🔒 Another Instance Already Running", [
                ("PID", "Unknown"),
            ])

    except (OSError, ValueError) as e:
        logger.error("🔒 Another Instance Already Running", [
            ("PID", "Could not read"),
            ("Error", str(e)),
        ])


# =============================================================================
# Cleanup Functions
# =============================================================================

def cleanup_temp_files() -> None:
    """
    Clean up temporary files from previous runs.

    Removes any stale temp files that might have been left
    from previous bot runs or crashes.

    NOTE: Excludes the lock file (azab_bot.lock) which must persist.
    """
    temp_dir = Path("/tmp")
    cleaned = 0

    for pattern in ["azabbot_*", "azab_*"]:
        for temp_file in temp_dir.glob(pattern):
            # Skip the lock file - it must persist for single-instance enforcement
            if temp_file.name == "azab_bot.lock":
                continue
            try:
                if temp_file.is_file():
                    temp_file.unlink()
                    cleaned += 1
            except Exception:
                pass

    if cleaned > 0:
        logger.info("🧹 Temp Files Cleaned", [
            ("Files Removed", str(cleaned)),
        ])


# =============================================================================
# Main Entry Point
# =============================================================================

async def main() -> None:
    """
    Main entry point for Azab Discord bot.

    This function handles the complete bot lifecycle:
    1. Acquires single-instance lock
    2. Cleans up temp files from previous runs
    3. Loads and validates configuration
    4. Initializes bot instance
    5. Establishes connection to Discord API
    6. Handles graceful shutdown on interruption

    Raises:
        SystemExit: If bot token is missing or bot fails to start.
    """
    # Acquire single-instance lock (uses fcntl.flock - auto-releases on crash)
    lock_fd = acquire_lock()

    shutdown_event = asyncio.Event()

    # Signal handler for graceful shutdown
    def signal_handler(sig: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(sig).name
        logger.tree("📡 Signal Received", [
            ("Signal", sig_name),
            ("Action", "Initiating graceful shutdown"),
        ])
        shutdown_event.set()

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Clean up temp files from previous runs
    cleanup_temp_files()

    # Validate configuration at startup
    try:
        validate_and_log_config()
    except ConfigValidationError as e:
        logger.error("Configuration Validation Failed", [
            ("Error", str(e)),
            ("Action", "Check your .env file"),
        ])
        sys.exit(1)

    logger.tree(f"{BOT_NAME} Starting", [
        ("Run ID", RUN_ID),
        ("Started At", _get_start_time()),
        ("Version", _get_git_commit()),
        ("Host", platform.node()),
        ("PID", str(os.getpid())),
        ("Python", platform.python_version()),
        ("Developer", "حَـــــنَّـــــا"),
    ], emoji="🚀")

    token = os.getenv("AZAB_TOKEN")
    if not token:
        # This should not happen if validate_and_log_config() passed
        logger.error("Missing Discord Token", [
            ("Variable", "AZAB_TOKEN"),
            ("Solution", "Create .env file with AZAB_TOKEN=your_token_here"),
        ])
        sys.exit(1)

    bot: Optional[AzabBot] = None

    try:
        logger.info("🤖 Creating Azab Instance")
        bot = AzabBot()

        # Start bot task and watch for shutdown signal
        def bot_exception_handler(task: asyncio.Task) -> None:
            """Handle exceptions from bot task."""
            if task.cancelled():
                return
            exc = task.exception()
            if exc:
                logger.error("💥 Bot Task Exception", [
                    ("Error", str(exc)[:100]),
                    ("Action", "Shutdown triggered"),
                ])
                shutdown_event.set()

        bot_task = asyncio.create_task(bot.start(token))
        bot_task.add_done_callback(bot_exception_handler)
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        # Create a ready waiter task
        async def wait_for_ready():
            await bot.wait_until_ready()
            return True

        ready_task = asyncio.create_task(wait_for_ready())

        # Wait for ready, shutdown, or startup timeout (60 seconds)
        startup_timeout = 60
        try:
            done, pending = await asyncio.wait(
                [ready_task, shutdown_task, bot_task],
                timeout=startup_timeout,
                return_when=asyncio.FIRST_COMPLETED
            )

            if ready_task in done:
                logger.success("Discord Connection Established", [
                    ("Guilds", str(len(bot.guilds))),
                    ("Latency", f"{bot.latency * 1000:.0f}ms"),
                ])
            elif bot_task in done:
                if bot_task.exception():
                    raise bot_task.exception()
            elif shutdown_task in done:
                logger.info("🛑 Shutdown Requested During Startup")
            else:
                # Timeout
                logger.error("⏰ Startup Timeout", [
                    ("Timeout", f"{startup_timeout}s"),
                    ("Action", "Aborting startup"),
                ])
                for task in [ready_task, bot_task]:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                raise RuntimeError(f"Bot failed to connect within {startup_timeout}s")

            # Cancel ready task if still pending
            if ready_task in pending:
                ready_task.cancel()
                try:
                    await ready_task
                except asyncio.CancelledError:
                    pass

        except asyncio.TimeoutError:
            logger.error("⏰ Startup Timeout", [
                ("Timeout", f"{startup_timeout}s"),
            ])
            ready_task.cancel()
            bot_task.cancel()
            raise RuntimeError(f"Bot failed to connect within {startup_timeout}s")

        # Wait for either bot to finish or shutdown signal
        done, pending = await asyncio.wait(
            [bot_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except KeyboardInterrupt:
        logger.tree("✋ Keyboard Interrupt", [
            ("Action", "Shutdown requested"),
            ("Method", "Ctrl+C"),
        ])

    except discord.LoginFailure as e:
        logger.error("🔐 Discord Authentication Failed", [
            ("Error", str(e)[:100]),
            ("Solution", "Check your AZAB_TOKEN in .env file"),
        ])

    except discord.PrivilegedIntentsRequired as e:
        logger.error("🔒 Missing Required Discord Intents", [
            ("Error", str(e)[:100]),
            ("Solution", "Enable intents in Discord Developer Portal"),
        ])

    except Exception as e:
        logger.error("💥 Fatal Error Occurred", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:100]),
        ])
        logger.exception("Full traceback:")

    finally:
        if bot:
            try:
                logger.info("🔄 Graceful Shutdown")
                await bot.close()
            except Exception as e:
                logger.error("Error during shutdown", [
                    ("Error", str(e)[:50]),
                ])

        # Close lock file descriptor (lock auto-releases)
        try:
            os.close(lock_fd)
        except OSError:
            pass

        logger.success("🛑 Azab Bot Shutdown Complete")


# =============================================================================
# Script Execution
# =============================================================================

if __name__ == "__main__":
    """
    Script entry point for direct execution.

    Sets working directory and runs the main async function.
    Handles KeyboardInterrupt gracefully for clean shutdown.
    """
    project_root = Path(__file__).parent
    os.chdir(project_root)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✋ Bot stopped by user")
        logger.tree("✋ Application Terminated", [
            ("Terminated By", "User"),
            ("Method", "Keyboard interrupt"),
        ])
    except SystemExit:
        raise
    except Exception as e:
        logger.error("💥 Unhandled Exception in Main", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:100]),
        ])
        print(f"\n❌ Critical Error: {e}")
        sys.exit(1)
