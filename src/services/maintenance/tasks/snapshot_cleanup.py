"""
AzabBot - Snapshot Cleanup Task
===============================

Cleans up old user snapshots for users without moderation history.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.config import get_config
from src.services.maintenance.base import MaintenanceTask
from src.services.user_snapshots import cleanup_old_snapshots

if TYPE_CHECKING:
    from src.bot import AzabBot


class SnapshotCleanupTask(MaintenanceTask):
    """
    Clean up old user snapshots.

    Removes snapshots older than 1 year for users who have no
    moderation cases. Users with cases keep their snapshots forever.
    """

    name = "Snapshot Cleanup"

    async def should_run(self) -> bool:
        """Always run this cleanup task."""
        return True

    async def run(self) -> Dict[str, Any]:
        """Clean up old snapshots."""
        config = get_config()
        guild_id = config.logging_guild_id

        if not guild_id:
            return {"success": False, "deleted": 0, "error": "No guild configured"}

        try:
            deleted = cleanup_old_snapshots(guild_id, days_old=365)

            if deleted > 0:
                logger.tree("Snapshot Cleanup Complete", [
                    ("Deleted", str(deleted)),
                    ("Older Than", "365 days"),
                    ("Note", "Users with cases preserved"),
                ], emoji="🧹")

            return {"success": True, "deleted": deleted}

        except Exception as e:
            logger.error("Snapshot Cleanup Failed", [
                ("Error", str(e)[:100]),
            ])
            return {"success": False, "deleted": 0, "error": str(e)[:100]}


__all__ = ["SnapshotCleanupTask"]
