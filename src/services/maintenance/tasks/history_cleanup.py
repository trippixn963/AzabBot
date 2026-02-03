"""
AzabBot - History Cleanup Task
==============================

Delete old username and nickname history records.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.config import NY_TZ
from src.core.constants import LOG_TRUNCATE_SHORT, HISTORY_RETENTION_DAYS
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class HistoryCleanupTask(MaintenanceTask):
    """
    Clean up old username and nickname history records.

    Deletes records older than HISTORY_RETENTION_DAYS to prevent
    the database from growing indefinitely.
    """

    name = "History Cleanup"

    async def should_run(self) -> bool:
        """Check if database is available."""
        return self.bot.db is not None

    async def run(self) -> Dict[str, Any]:
        """Delete old history records."""
        username_deleted = 0
        nickname_deleted = 0
        errors = 0

        try:
            cutoff = datetime.now(NY_TZ) - timedelta(days=HISTORY_RETENTION_DAYS)
            cutoff_ts = cutoff.timestamp()

            # Clean old username history
            try:
                result = self.bot.db.execute(
                    "DELETE FROM username_history WHERE changed_at < ?",
                    (cutoff_ts,)
                )
                if result:
                    username_deleted = result.rowcount
            except Exception as e:
                errors += 1
                logger.error("Username History Cleanup Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # Clean old nickname history
            try:
                result = self.bot.db.execute(
                    "DELETE FROM nickname_history WHERE changed_at < ?",
                    (cutoff_ts,)
                )
                if result:
                    nickname_deleted = result.rowcount
            except Exception as e:
                errors += 1
                logger.error("Nickname History Cleanup Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            total_deleted = username_deleted + nickname_deleted

            if total_deleted > 0:
                logger.tree("History Cleanup Complete", [
                    ("Username Records", str(username_deleted)),
                    ("Nickname Records", str(nickname_deleted)),
                    ("Retention", f"{HISTORY_RETENTION_DAYS} days"),
                ], emoji="🧹")

            return {
                "success": errors == 0,
                "deleted": total_deleted,
                "username_deleted": username_deleted,
                "nickname_deleted": nickname_deleted,
                "errors": errors,
            }

        except Exception as e:
            logger.error("History Cleanup Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        deleted = result.get("deleted", 0)
        return f"{deleted} deleted" if deleted > 0 else "clean"


__all__ = ["HistoryCleanupTask"]
