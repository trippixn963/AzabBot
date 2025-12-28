"""
Azab Discord Bot - Case Archive Scheduler
==========================================

Background service for automatic deletion of old case threads.

DESIGN:
    Runs as a background task checking for threads older than 7 days.
    Deletes old threads to keep the case logs forum clean.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import discord
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
from src.core.database import get_db

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

CASE_RETENTION_DAYS = 7
CHECK_INTERVAL_HOURS = 1


# =============================================================================
# Case Archive Scheduler
# =============================================================================

class CaseArchiveScheduler:
    """
    Background service for automatic case thread deletion.

    DESIGN:
        Runs a loop every hour checking for old case threads.
        Deletes threads older than 7 days from the case logs forum.
        Gracefully handles errors without crashing the loop.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
        task: Background task reference.
        running: Whether the scheduler is active.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the case archive scheduler.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self.task: Optional[asyncio.Task] = None
        self.running: bool = False

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start(self) -> None:
        """
        Start the case archive scheduler background task.

        DESIGN:
            Cancels any existing task before starting new one.
        """
        if self.task and not self.task.done():
            self.task.cancel()

        self.running = True
        self.task = asyncio.create_task(self._scheduler_loop())

        logger.tree("Case Archive Scheduler Started", [
            ("Retention", f"{CASE_RETENTION_DAYS} days"),
            ("Check Interval", f"{CHECK_INTERVAL_HOURS} hour(s)"),
        ], emoji="🗑️")

    async def stop(self) -> None:
        """
        Stop the case archive scheduler background task.
        """
        self.running = False

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("Case Archive Scheduler Stopped")

    # =========================================================================
    # Scheduler Loop
    # =========================================================================

    async def _scheduler_loop(self) -> None:
        """
        Main scheduler loop.

        DESIGN:
            Runs every hour checking for old case threads.
            Continues running even if individual deletions fail.
        """
        await self.bot.wait_until_ready()

        # Wait a bit on startup to let other services initialize
        await asyncio.sleep(60)

        while self.running:
            try:
                await self._process_old_cases()
                await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Case Archive Scheduler Error", [
                    ("Error", str(e)[:100]),
                ])
                # Send error alert to webhook
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Archive Scheduler Error",
                        str(e)[:500]
                    )
                await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)

    # =========================================================================
    # Case Processing
    # =========================================================================

    async def _process_old_cases(self) -> None:
        """
        Process all old cases and delete their threads.

        DESIGN:
            Gets cases older than 7 days from database.
            Deletes the forum thread for each case.
            Marks the case as archived in the database.
        """
        cutoff_time = datetime.now(NY_TZ) - timedelta(days=CASE_RETENTION_DAYS)
        old_cases = self.db.get_old_cases(cutoff_time.timestamp())

        if not old_cases:
            return

        deleted_count = 0
        failed_count = 0

        for case in old_cases:
            case_id = case.get("case_id")
            if not case_id:
                failed_count += 1
                continue

            try:
                # Mark case as archived FIRST (before Discord action)
                # This prevents race condition if bot crashes during thread deletion
                self.db.archive_case(case_id)

                # Then delete the thread
                success = await self._delete_case_thread(case)
                if success:
                    deleted_count += 1
                else:
                    # Thread deletion failed, but case is already archived
                    # This is acceptable - thread may already be deleted
                    deleted_count += 1
            except Exception as e:
                logger.error("Failed To Delete Case Thread", [
                    ("Case ID", case_id),
                    ("Error", str(e)[:100]),
                ])
                failed_count += 1

        if deleted_count > 0 or failed_count > 0:
            logger.tree("Case Archive Cleanup", [
                ("Deleted", str(deleted_count)),
                ("Failed", str(failed_count)),
                ("Total Checked", str(len(old_cases))),
            ], emoji="🗑️")

    async def _delete_case_thread(self, case: dict) -> bool:
        """
        Delete a case thread from the forum.

        Args:
            case: Case record from database.

        Returns:
            True if successfully deleted, False otherwise.
        """
        thread_id = case.get("thread_id")
        if not thread_id:
            return False

        try:
            thread = self.bot.get_channel(thread_id)
            if not thread:
                # Try to fetch it
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                except discord.NotFound:
                    # Thread already deleted
                    return True
                except discord.HTTPException:
                    return False

            if thread:
                await thread.delete(reason=f"Case archive: Thread older than {CASE_RETENTION_DAYS} days")
                return True

        except discord.NotFound:
            # Thread already deleted
            return True
        except discord.Forbidden:
            logger.warning("No Permission To Delete Thread", [
                ("Thread ID", str(thread_id)),
                ("Case ID", case.get("case_id", "Unknown")),
            ])
            return False
        except discord.HTTPException as e:
            logger.error("HTTP Error Deleting Thread", [
                ("Thread ID", str(thread_id)),
                ("Error", str(e)[:50]),
            ])
            return False

        return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CaseArchiveScheduler"]
