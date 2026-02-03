"""
AzabBot - Maintenance Task Base Class
=====================================

Base class for all maintenance tasks.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from src.bot import AzabBot


class MaintenanceTask(ABC):
    """
    Abstract base class for maintenance tasks.

    All maintenance tasks should inherit from this class and implement
    the required methods.
    """

    # Task name for logging (override in subclass)
    name: str = "Unknown Task"

    # Whether this task is enabled by default
    enabled_by_default: bool = True

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot

    @abstractmethod
    async def should_run(self) -> bool:
        """
        Check if this task should run.

        Override to add conditions like checking if required
        config values are set.

        Returns:
            True if the task should run, False otherwise.
        """
        pass

    @abstractmethod
    async def run(self) -> Dict[str, Any]:
        """
        Execute the maintenance task.

        Returns:
            Dict with task results for logging. Should include at minimum:
            - "success": bool
            - Any other relevant stats (e.g., "fixed": 5, "errors": 0)
        """
        pass

    def format_result(self, result: Dict[str, Any]) -> str:
        """
        Format the task result for the summary log.

        Override for custom formatting.

        Args:
            result: The dict returned by run()

        Returns:
            Short string describing the result (e.g., "3 fixed")
        """
        if not result.get("success", False):
            return "failed"

        # Try common result keys
        if "fixed" in result:
            return f"{result['fixed']} fixed"
        if "deleted" in result:
            return f"{result['deleted']} deleted"
        if "cleaned" in result:
            return f"{result['cleaned']} cleaned"
        if "scanned" in result:
            return f"{result['scanned']} scanned"

        return "done"


__all__ = ["MaintenanceTask"]
