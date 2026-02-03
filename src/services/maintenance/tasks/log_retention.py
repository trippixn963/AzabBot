"""
AzabBot - Log Retention Cleanup Task
====================================

Delete log messages older than retention period.

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


class LogRetentionTask(MaintenanceTask):
    """
    Delete log messages older than the configured retention period.

    Also validates utility threads in the logging forum.
    """

    name = "Log Retention"

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(bot)
        self.config = get_config()

    async def should_run(self) -> bool:
        """Check if logging service is enabled and retention is configured."""
        return (
            self.bot.logging_service is not None
            and self.bot.logging_service.enabled
            and self.config.log_retention_days > 0
        )

    async def run(self) -> Dict[str, Any]:
        """Run log retention cleanup."""
        try:
            # Delegate to the logging service's existing methods
            await self.bot.logging_service._cleanup_old_logs()
            await self.bot.logging_service._validate_utility_threads()
            return {"success": True}
        except Exception as e:
            logger.error("Log Retention Task Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return "cleaned" if result.get("success") else "failed"


__all__ = ["LogRetentionTask"]
