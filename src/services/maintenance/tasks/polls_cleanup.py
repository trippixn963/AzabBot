"""
AzabBot - Polls Cleanup Task
============================

Clean up poll result messages from polls-only channels.

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


class PollsCleanupTask(MaintenanceTask):
    """
    Scan and clean poll result messages from polls-only channels.

    This ensures polls channels only contain active polls, not
    the result messages that appear after a poll ends.
    """

    name = "Polls Cleanup"

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(bot)
        self.config = get_config()

    async def should_run(self) -> bool:
        """Check if polls channels are configured."""
        return bool(self.config.polls_only_channel_ids)

    async def run(self) -> Dict[str, Any]:
        """Run polls cleanup scan."""
        try:
            # Delegate to the bot's existing method
            await self.bot._scan_and_clean_poll_results()
            return {"success": True}
        except Exception as e:
            logger.error("Polls Cleanup Task Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return "cleaned" if result.get("success") else "failed"


__all__ = ["PollsCleanupTask"]
