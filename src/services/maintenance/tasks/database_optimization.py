"""
AzabBot - Database Optimization Task
====================================

Run SQLite VACUUM to reclaim space and optimize performance.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class DatabaseOptimizationTask(MaintenanceTask):
    """
    Run SQLite VACUUM to optimize database performance.

    VACUUM rebuilds the database file, repacking it into a minimal
    amount of disk space. This is beneficial after many deletions.
    """

    name = "Database Optimization"

    async def should_run(self) -> bool:
        """Always run database optimization."""
        return self.bot.db is not None

    async def run(self) -> Dict[str, Any]:
        """Run VACUUM on the database."""
        try:
            # Run VACUUM to optimize database
            self.bot.db.execute("VACUUM")

            # Also run ANALYZE to update query planner statistics
            self.bot.db.execute("ANALYZE")

            logger.tree("Database Optimization Complete", [
                ("VACUUM", "Done"),
                ("ANALYZE", "Done"),
            ], emoji="🗄️")

            return {"success": True}
        except Exception as e:
            logger.error("Database Optimization Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return "optimized" if result.get("success") else "failed"


__all__ = ["DatabaseOptimizationTask"]
