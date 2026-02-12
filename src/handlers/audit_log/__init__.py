"""
AzabBot - Audit Log Events Package
==================================

Handles audit log entries and routes them to mod_tracker and logging_service.

Structure:
    - antinuke.py: Anti-nuke detection routing
    - mod_tracker.py: Mod tracker routing with helper methods
    - logging.py: Logging service routing with helper methods
    - cog.py: Main AuditLogEvents cog with event listeners

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.core.logger import logger

from .cog import AuditLogEvents

if TYPE_CHECKING:
    from src.bot import AzabBot

__all__ = ["AuditLogEvents"]


async def setup(bot: "AzabBot") -> None:
    """Load the AuditLogEvents cog."""
    await bot.add_cog(AuditLogEvents(bot))
    logger.tree("Audit Log Events Loaded", [
        ("Events", "on_audit_log_entry_create"),
        ("Features", "mod tracker, logging service"),
    ], emoji="📋")
