"""
AzabBot - Maintenance Service
=============================

Centralized service for running scheduled maintenance tasks at midnight EST.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from src.core.logger import logger
from src.core.config import NY_TZ
from src.core.constants import LOG_TRUNCATE_SHORT, SECONDS_PER_HOUR
from src.utils.async_utils import create_safe_task

from .base import MaintenanceTask
from .tasks import (
    GenderRoleTask,
    GuildProtectionTask,
    MuteOverwritesTask,
    ModTrackerScanTask,
    ModInactivityTask,
    LogRetentionTask,
    PrisonCleanupTask,
    PollsCleanupTask,
    ForbidOverwritesTask,
    PrisonerTrackingTask,
    DatabaseOptimizationTask,
    StaleMuteCleanupTask,
    HistoryCleanupTask,
    InviteCacheRefreshTask,
    CaseThreadValidationTask,
    JoinInfoCleanupTask,
    SnapshotCleanupTask,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


class MaintenanceService:
    """
    Centralized service for running scheduled maintenance tasks.

    All tasks run at midnight EST. Each task is modular and can be
    enabled/disabled independently based on configuration.
    """

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self._last_run_date: Optional[str] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Register all maintenance tasks
        self._tasks: List[MaintenanceTask] = [
            # Core protection
            GuildProtectionTask(bot),
            GenderRoleTask(bot),
            # Permission syncs
            MuteOverwritesTask(bot),
            ForbidOverwritesTask(bot),
            # Mod tracker
            ModTrackerScanTask(bot),
            ModInactivityTask(bot),
            # Cleanup tasks
            LogRetentionTask(bot),
            PrisonCleanupTask(bot),
            PollsCleanupTask(bot),
            PrisonerTrackingTask(bot),
            StaleMuteCleanupTask(bot),
            HistoryCleanupTask(bot),
            JoinInfoCleanupTask(bot),
            SnapshotCleanupTask(bot),
            # Validation & optimization
            CaseThreadValidationTask(bot),
            InviteCacheRefreshTask(bot),
            DatabaseOptimizationTask(bot),  # Run last after all deletions
        ]

        # Log loaded tasks
        task_names = [t.name for t in self._tasks]
        logger.tree("Maintenance Service Loaded", [
            ("Schedule", "Daily at midnight EST"),
            ("Tasks", ", ".join(task_names)),
            ("Total", str(len(self._tasks))),
        ], emoji="🔧")

    def start(self) -> None:
        """Start the maintenance scheduler."""
        if self._running:
            return

        self._running = True
        self._task = create_safe_task(self._scheduler_loop(), "Maintenance Scheduler")
        logger.info("Maintenance Scheduler Started")

    async def stop(self) -> None:
        """Stop the maintenance scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Maintenance Scheduler Stopped")

    async def _scheduler_loop(self) -> None:
        """Main loop that waits for midnight and runs tasks."""
        await self.bot.wait_until_ready()

        while self._running:
            try:
                # Calculate time until next midnight EST
                now = datetime.now(NY_TZ)
                target = now.replace(hour=0, minute=0, second=0, microsecond=0)

                # If past midnight, schedule for tomorrow
                if now >= target:
                    from datetime import timedelta
                    target = target + timedelta(days=1)

                seconds_until = (target - now).total_seconds()

                logger.tree("Maintenance Scheduled", [
                    ("Next Run", target.strftime("%Y-%m-%d %I:%M %p EST")),
                    ("Sleep", f"{seconds_until / 3600:.1f} hours"),
                ], emoji="⏰")

                # Wait until midnight
                await asyncio.sleep(seconds_until)

                # Run all tasks
                await self.run_all_tasks()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Maintenance Scheduler Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                    ("Retry", "1 hour"),
                ])
                await asyncio.sleep(SECONDS_PER_HOUR)

    async def run_all_tasks(self) -> None:
        """
        Run all maintenance tasks.

        Can be called manually or by the scheduler at midnight.
        """
        now = datetime.now(NY_TZ)
        today = now.strftime("%Y-%m-%d")

        # Prevent duplicate runs on same day
        if self._last_run_date == today:
            logger.debug("Maintenance tasks already ran today, skipping")
            return

        self._last_run_date = today

        logger.tree("Midnight Maintenance Starting", [
            ("Date", today),
            ("Time", now.strftime("%I:%M %p EST")),
            ("Tasks", str(len(self._tasks))),
        ], emoji="🌙")

        results = []

        for task in self._tasks:
            try:
                # Check if task should run
                if not await task.should_run():
                    logger.debug("Task Skipped", [("Task", task.name), ("Reason", "Conditions not met")])
                    continue

                # Run the task
                result = await task.run()
                result_str = task.format_result(result)
                results.append(f"{task.name} ({result_str})")

            except Exception as e:
                logger.error("Maintenance Task Failed", [
                    ("Task", task.name),
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])
                results.append(f"{task.name} (error)")

        # Log summary
        logger.tree("Midnight Maintenance Complete", [
            ("Date", today),
            ("Tasks Run", str(len(results))),
            ("Results", ", ".join(results) if results else "None"),
        ], emoji="✅")


__all__ = ["MaintenanceService"]
