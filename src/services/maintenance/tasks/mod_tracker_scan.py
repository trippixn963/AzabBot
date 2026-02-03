"""
AzabBot - Mod Tracker Scan Task
===============================

Run comprehensive scan of all moderators at midnight.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class ModTrackerScanTask(MaintenanceTask):
    """
    Run a comprehensive scan of all moderators at midnight.

    This scan:
    1. Checks if tracked mods still have the mod role
    2. Removes tracking for mods who lost the role
    3. Adds tracking for new mods with the role
    4. Verifies all forum threads still exist
    5. Recreates missing threads
    6. Updates thread titles if names changed
    """

    name = "Mod Tracker"

    async def should_run(self) -> bool:
        """Check if mod tracker is enabled."""
        return self.bot.mod_tracker is not None and self.bot.mod_tracker.enabled

    async def run(self) -> Dict[str, Any]:
        """Run comprehensive mod tracker scan."""
        try:
            # Delegate to the mod tracker's existing method
            await self.bot.mod_tracker._run_comprehensive_scan()
            return {"success": True}
        except Exception as e:
            logger.error("Mod Tracker Scan Task Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return "scanned" if result.get("success") else "failed"


__all__ = ["ModTrackerScanTask"]
