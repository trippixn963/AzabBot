"""
AzabBot - Forbid Role Overwrites Task
=====================================

Scan all channels and ensure forbid roles have correct overwrites.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class ForbidOverwritesTask(MaintenanceTask):
    """
    Scan all channels and ensure forbid roles have correct overwrites.

    Each forbid type (reactions, attachments, voice, etc.) has its own role
    with specific permission overwrites that need to be maintained.
    """

    name = "Forbid Overwrites"

    async def should_run(self) -> bool:
        """Check if forbid cog is loaded."""
        return self.bot.get_cog("ForbidCog") is not None

    async def run(self) -> Dict[str, Any]:
        """Run forbid overwrites scan."""
        try:
            forbid_cog = self.bot.get_cog("ForbidCog")
            if forbid_cog:
                await forbid_cog._run_forbid_scan()
            return {"success": True}
        except Exception as e:
            logger.error("Forbid Overwrites Task Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return "scanned" if result.get("success") else "failed"


__all__ = ["ForbidOverwritesTask"]
