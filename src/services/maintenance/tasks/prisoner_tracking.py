"""
AzabBot - Prisoner Tracking Cleanup Task
========================================

Clean up prisoner tracking for users no longer muted.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.config import get_config
from src.core.constants import LOG_TRUNCATE_SHORT
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class PrisonerTrackingTask(MaintenanceTask):
    """
    Clean up prisoner tracking for users no longer muted.

    Removes entries from prisoner_cooldowns, prisoner_message_buffer,
    and prisoner_pending_response for users not currently muted.
    """

    name = "Prisoner Tracking"

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(bot)
        self.config = get_config()

    async def should_run(self) -> bool:
        """Check if muted role is configured."""
        return self.config.muted_role_id is not None

    async def run(self) -> Dict[str, Any]:
        """Clean up stale prisoner tracking entries."""
        try:
            cleaned = await self.bot._cleanup_prisoner_tracking()
            return {"success": True, "cleaned": cleaned}
        except Exception as e:
            logger.error("Prisoner Tracking Cleanup Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        cleaned = result.get("cleaned", 0)
        return f"{cleaned} cleaned" if cleaned > 0 else "clean"


__all__ = ["PrisonerTrackingTask"]
