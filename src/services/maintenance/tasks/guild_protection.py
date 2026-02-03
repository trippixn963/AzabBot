"""
AzabBot - Guild Protection Task
===============================

Leave unauthorized guilds at midnight.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class GuildProtectionTask(MaintenanceTask):
    """
    Leave any guilds that are not in the authorized list.

    This prevents the bot from being added to unauthorized servers.
    """

    name = "Guild Protection"

    async def should_run(self) -> bool:
        """Always run guild protection check."""
        return True

    async def run(self) -> Dict[str, Any]:
        """Check and leave unauthorized guilds."""
        try:
            # The bot has this method built-in
            await self.bot._leave_unauthorized_guilds()
            return {"success": True}
        except Exception as e:
            logger.error("Guild Protection Task Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return "checked" if result.get("success") else "failed"


__all__ = ["GuildProtectionTask"]
