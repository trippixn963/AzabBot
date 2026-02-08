"""
AzabBot - Latency Cleanup Task
==============================

Cleans up old latency data from the database.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any, Dict

from src.core.logger import logger
from src.services.maintenance.base import MaintenanceTask
from src.api.services.latency_storage import get_latency_storage


class LatencyCleanupTask(MaintenanceTask):
    """
    Clean up old latency data.

    Removes latency records older than 30 days to prevent
    database bloat from continuous recording.
    """

    name = "Latency Cleanup"

    async def should_run(self) -> bool:
        """Always run this cleanup task."""
        return True

    async def run(self) -> Dict[str, Any]:
        """Clean up old latency data."""
        try:
            latency_storage = get_latency_storage()
            deleted = latency_storage.cleanup_old_data()

            if deleted > 0:
                logger.tree("Latency Cleanup Complete", [
                    ("Deleted", f"{deleted:,} records"),
                    ("Older Than", "30 days"),
                ], emoji="🧹")

            return {"success": True, "deleted": deleted}

        except Exception as e:
            logger.error("Latency Cleanup Failed", [
                ("Error", str(e)[:100]),
            ])
            return {"success": False, "deleted": 0, "error": str(e)[:100]}


__all__ = ["LatencyCleanupTask"]
