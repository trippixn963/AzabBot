"""
AzabBot - Case Thread Validation Task
=====================================

Verify that case log threads still exist and are accessible.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

import discord

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT, QUERY_LIMIT_MEDIUM
from src.utils.discord_rate_limit import log_http_error
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class CaseThreadValidationTask(MaintenanceTask):
    """
    Validate that case log threads still exist.

    Checks recent case log entries and verifies the threads
    are still accessible. Marks invalid entries for cleanup.
    """

    name = "Case Thread Validation"

    async def should_run(self) -> bool:
        """Check if case log service is available."""
        return self.bot.case_log_service is not None and self.bot.db is not None

    async def run(self) -> Dict[str, Any]:
        """Validate case log threads."""
        validated = 0
        missing = 0
        errors = 0

        try:
            # Get recent case logs with thread IDs
            rows = self.bot.db.fetchall(
                """SELECT case_id, thread_id, channel_id
                   FROM case_logs
                   WHERE thread_id IS NOT NULL
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (QUERY_LIMIT_MEDIUM,)
            )

            if not rows:
                return {"success": True, "validated": 0, "missing": 0}

            for row in rows:
                thread_id = row["thread_id"]

                try:
                    # Try to fetch the thread
                    thread = self.bot.get_channel(thread_id)
                    if thread is None:
                        # Try fetching from API
                        try:
                            thread = await self.bot.fetch_channel(thread_id)
                        except discord.NotFound:
                            thread = None
                        except discord.HTTPException:
                            errors += 1
                            continue

                    if thread is None:
                        missing += 1
                        # Optionally mark as invalid in database
                        self.bot.db.execute(
                            "UPDATE case_logs SET thread_id = NULL WHERE thread_id = ?",
                            (thread_id,)
                        )
                    else:
                        validated += 1

                except Exception as e:
                    errors += 1
                    logger.debug("Thread Validation Error", [("Error", str(e)[:50])])

            if missing > 0:
                logger.tree("Case Thread Validation Complete", [
                    ("Validated", str(validated)),
                    ("Missing Threads", str(missing)),
                    ("Errors", str(errors)),
                ], emoji="🔍")

            return {
                "success": True,
                "validated": validated,
                "missing": missing,
                "errors": errors,
            }

        except Exception as e:
            logger.error("Case Thread Validation Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        validated = result.get("validated", 0)
        missing = result.get("missing", 0)
        if missing > 0:
            return f"{missing} missing"
        return f"{validated} valid"


__all__ = ["CaseThreadValidationTask"]
