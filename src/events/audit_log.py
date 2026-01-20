"""
Azab Discord Bot - Audit Log Events
====================================

Handles audit log entries and routes them to mod_tracker and logging_service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger
from src.events.audit_log.cog import AuditLogEvents

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Add the audit log events cog to the bot."""
    await bot.add_cog(AuditLogEvents(bot))
    logger.debug("Audit Log Events Loaded")


__all__ = ["AuditLogEvents", "setup"]
