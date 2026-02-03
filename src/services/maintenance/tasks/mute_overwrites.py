"""
AzabBot - Mute Role Overwrites Task
===================================

Scan all channels and ensure muted role has correct overwrites.

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


class MuteOverwritesTask(MaintenanceTask):
    """
    Scan all channels and ensure muted role has correct overwrites.

    For regular channels/categories:
        - send_messages = False
        - view_channel = False (prisoners can't see other channels)

    For prison channels:
        - send_messages = True
        - view_channel = True
    """

    name = "Mute Overwrites"

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(bot)
        self.config = get_config()

    async def should_run(self) -> bool:
        """Check if mute scheduler is available."""
        return self.bot.mute_scheduler is not None and self.config.muted_role_id is not None

    async def run(self) -> Dict[str, Any]:
        """Scan and fix mute role overwrites."""
        try:
            # Delegate to the mute scheduler's existing method
            await self.bot.mute_scheduler._scan_mute_role_overwrites()
            return {"success": True}
        except Exception as e:
            logger.error("Mute Overwrites Task Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return "scanned" if result.get("success") else "failed"


__all__ = ["MuteOverwritesTask"]
