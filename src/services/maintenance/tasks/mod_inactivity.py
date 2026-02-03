"""
AzabBot - Mod Inactivity Check Task
===================================

Check all tracked mods for inactivity and send alerts.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class ModInactivityTask(MaintenanceTask):
    """
    Check all tracked moderators for inactivity.

    Sends alerts to mod threads if a moderator hasn't performed
    any mod actions within the configured inactivity threshold.
    """

    name = "Mod Inactivity"

    async def should_run(self) -> bool:
        """Check if mod tracker is enabled."""
        return self.bot.mod_tracker is not None and self.bot.mod_tracker.enabled

    async def run(self) -> Dict[str, Any]:
        """Check for inactive mods and send alerts."""
        try:
            # Delegate to the mod tracker's existing method
            await self.bot.mod_tracker._check_inactive_mods()
            return {"success": True}
        except Exception as e:
            logger.error("Mod Inactivity Task Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return "checked" if result.get("success") else "failed"


__all__ = ["ModInactivityTask"]
