"""
Audit Log Events - Main Cog
===========================

Handles audit log entries and routes them to mod_tracker and logging_service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config

from .antinuke import AntiNukeMixin
from .mod_tracker import ModTrackerMixin
from .logging import LoggingMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class AuditLogEvents(AntiNukeMixin, ModTrackerMixin, LoggingMixin, commands.Cog):
    """Audit log event handlers."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

        logger.tree("Audit Log Events Loaded", [
            ("Anti-Nuke", "Enabled"),
            ("Mod Tracker", "Routing enabled"),
            ("Server Logs", "Routing enabled"),
        ], emoji="📋")

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        """
        Track mod actions via audit log entries.

        DESIGN: Uses audit log to identify which mod performed actions.
        Routes events to both mod_tracker and logging_service.
        """
        # Route to anti-nuke service
        await self._check_antinuke(entry)

        # Route to logging service
        await self._log_audit_event(entry)

        # Route to mod tracker
        await self._track_mod_action(entry)


__all__ = ["AuditLogEvents"]
