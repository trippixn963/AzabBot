"""
Case Log Service - Reason Scheduler
===================================

Mixin for pending reason scheduler.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, Optional

from src.core.logger import logger
from src.utils.async_utils import create_safe_task

from .constants import (
    REASON_CHECK_INTERVAL,
    REASON_EXPIRY_TIME,
    REASON_CLEANUP_AGE,
)

if TYPE_CHECKING:
    from .service import CaseLogService


class CaseLogSchedulerMixin:
    """Mixin for pending reason scheduler."""

    # =========================================================================
    # Pending Reason Scheduler
    # =========================================================================

    async def start_reason_scheduler(self: "CaseLogService") -> None:
        """Start the background task for checking expired pending reasons."""
        if self._reason_check_task and not self._reason_check_task.done():
            self._reason_check_task.cancel()

        # Ensure forum tags exist on startup
        await self.ensure_forum_tags()

        self._reason_check_running = True
        self._reason_check_task = create_safe_task(
            self._reason_check_loop(), "Case Log Reason Checker"
        )

        logger.tree("Pending Reason Scheduler Started", [
            ("Check Interval", "5 minutes"),
            ("Expiry Time", "1 hour"),
        ], emoji="⏰")

    async def stop_reason_scheduler(self: "CaseLogService") -> None:
        """Stop the pending reason scheduler."""
        self._reason_check_running = False

        if self._reason_check_task and not self._reason_check_task.done():
            self._reason_check_task.cancel()
            try:
                await self._reason_check_task
            except asyncio.CancelledError:
                pass

        logger.tree("Pending Reason Scheduler Stopped", [
            ("Status", "Inactive"),
        ], emoji="⏹️")

    async def _reason_check_loop(self: "CaseLogService") -> None:
        """Background loop to check for expired pending reasons."""
        await self.bot.wait_until_ready()

        while self._reason_check_running:
            try:
                await self._process_expired_reasons()
                await asyncio.sleep(REASON_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Pending Reason Scheduler Error", [
                    ("Error", str(e)[:100]),
                ])
                await asyncio.sleep(REASON_CHECK_INTERVAL)

    async def _process_expired_reasons(self: "CaseLogService") -> None:
        """Process expired pending reasons (cleanup only, no owner ping)."""
        self.db.cleanup_old_pending_reasons(max_age_seconds=REASON_CLEANUP_AGE)
        expired = self.db.get_expired_pending_reasons(max_age_seconds=REASON_EXPIRY_TIME)

        for pending in expired:
            try:
                # Just mark as processed and clean up - no owner ping needed
                self.db.mark_pending_reason_notified(pending["id"])

                logger.tree("Missing Reason Expired", [
                    ("Thread ID", str(pending["thread_id"])),
                    ("Moderator ID", str(pending["moderator_id"])),
                    ("Action", pending["action_type"]),
                ], emoji="⚠️")

            except Exception as e:
                logger.error("Failed To Process Expired Reason", [
                    ("Pending ID", str(pending["id"])),
                    ("Error", str(e)[:50]),
                ])


__all__ = ["CaseLogSchedulerMixin"]
