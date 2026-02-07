"""
AzabBot - Resolved Case Cleanup Task
====================================

Delete Discord threads for resolved cases and clear thread_ids.

This is a one-time cleanup task for legacy resolved cases that still have
Discord threads. The transcripts are preserved in the database.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT
from src.utils.discord_rate_limit import log_http_error
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class ResolvedCaseCleanupTask(MaintenanceTask):
    """
    Delete Discord threads for resolved cases.

    Finds all resolved cases that still have thread_ids set,
    deletes the Discord threads, and clears the thread_ids.
    Case data and transcripts are preserved in the database.
    """

    name = "Resolved Case Cleanup"

    async def should_run(self) -> bool:
        """Check if database is available."""
        return self.bot.db is not None

    async def run(self) -> Dict[str, Any]:
        """Clean up resolved case threads."""
        deleted_count = 0
        already_deleted = 0
        failed_count = 0
        cleared_count = 0

        try:
            # Get all resolved cases with thread_ids
            cases = self.bot.db.get_resolved_cases_with_threads()

            if not cases:
                return {
                    "success": True,
                    "message": "No resolved cases with threads",
                    "deleted": 0,
                    "cleared": 0,
                }

            total_cases = len(cases)

            for case in cases:
                case_id = case.get("case_id")
                thread_id = case.get("thread_id")

                if not case_id or not thread_id:
                    continue

                try:
                    # Try to delete the Discord thread
                    thread_deleted = await self._delete_thread(thread_id, case_id)

                    if thread_deleted:
                        deleted_count += 1
                    else:
                        # Thread was already deleted or not found
                        already_deleted += 1

                    # Clear thread_id in database regardless
                    if self.bot.db.clear_case_thread_id(case_id):
                        cleared_count += 1

                except Exception as e:
                    failed_count += 1
                    logger.warning("Resolved Case Cleanup Failed", [
                        ("Case ID", case_id),
                        ("Thread ID", str(thread_id)),
                        ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                    ])

            if deleted_count > 0 or cleared_count > 0:
                logger.tree("Resolved Case Cleanup Complete", [
                    ("Total Cases", str(total_cases)),
                    ("Threads Deleted", str(deleted_count)),
                    ("Already Deleted", str(already_deleted)),
                    ("Thread IDs Cleared", str(cleared_count)),
                    ("Failed", str(failed_count)),
                ], emoji="🧹")

            return {
                "success": failed_count == 0,
                "total": total_cases,
                "deleted": deleted_count,
                "already_deleted": already_deleted,
                "cleared": cleared_count,
                "failed": failed_count,
            }

        except Exception as e:
            logger.error("Resolved Case Cleanup Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    async def _delete_thread(self, thread_id: int, case_id: str) -> bool:
        """
        Delete a Discord thread.

        Args:
            thread_id: The thread ID to delete.
            case_id: The case ID for logging.

        Returns:
            True if thread was deleted, False if already deleted/not found.
        """
        try:
            # Try to get thread from cache first
            thread = self.bot.get_channel(thread_id)

            if not thread:
                # Try to fetch from API
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                except discord.NotFound:
                    # Thread already deleted
                    return False
                except discord.HTTPException:
                    return False

            if thread:
                await thread.delete(reason=f"Resolved case cleanup: {case_id}")
                return True

        except discord.NotFound:
            # Thread already deleted
            return False
        except discord.Forbidden:
            logger.warning("No Permission To Delete Thread", [
                ("Thread ID", str(thread_id)),
                ("Case ID", case_id),
            ])
            return False
        except discord.HTTPException as e:
            log_http_error(e, "Delete Resolved Case Thread", [
                ("Thread ID", str(thread_id)),
                ("Case ID", case_id),
            ])
            return False

        return False

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        deleted = result.get("deleted", 0)
        cleared = result.get("cleared", 0)
        if deleted > 0 or cleared > 0:
            return f"{deleted} deleted, {cleared} cleared"
        return "clean"


__all__ = ["ResolvedCaseCleanupTask"]
