"""
AzabBot - Auto-Close Mixin
==========================

Auto-close logic for inactive tickets.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.constants import AUTO_CLOSE_CHECK_INTERVAL, THREAD_DELETE_DELAY
from src.utils.discord_rate_limit import log_http_error

from .constants import (
    INACTIVE_WARNING_DAYS,
    INACTIVE_CLOSE_DAYS,
)
from .embeds import build_inactivity_warning

if TYPE_CHECKING:
    from .service import TicketService


class AutoCloseMixin:
    """Mixin for auto-close functionality."""

    async def _auto_close_loop(self: "TicketService") -> None:
        """Background task to check for inactive tickets."""
        await self.bot.wait_until_ready()

        while self._running:
            try:
                await self._check_inactive_tickets()
            except Exception as e:
                logger.error("Auto-close check failed", [("Error", str(e))])

            await asyncio.sleep(AUTO_CLOSE_CHECK_INTERVAL)

    async def _check_inactive_tickets(self: "TicketService") -> None:
        """Check and handle inactive tickets."""
        if not self.config.main_guild_id:
            return

        guild_id = self.config.main_guild_id
        now = time.time()
        warning_threshold = now - (INACTIVE_WARNING_DAYS * 86400)
        close_threshold = now - (INACTIVE_CLOSE_DAYS * 86400)
        delete_threshold = now - THREAD_DELETE_DELAY  # 1 hour after close

        # Get tickets that need warning
        unwarned_tickets = self.db.get_unwarned_inactive_tickets(
            guild_id, warning_threshold
        )
        for ticket in unwarned_tickets:
            await self._send_inactivity_warning(ticket)

        # Get tickets that need closing
        warned_tickets = self.db.get_warned_tickets_ready_to_close(
            guild_id, close_threshold
        )
        for ticket in warned_tickets:
            await self._auto_close_ticket(ticket)

        # Get closed tickets that need deletion
        closed_tickets = self.db.get_closed_tickets_ready_to_delete(
            guild_id, delete_threshold
        )
        for ticket in closed_tickets:
            await self._auto_delete_ticket(ticket)

    async def _send_inactivity_warning(self: "TicketService", ticket: dict) -> None:
        """Send inactivity warning to ticket channel."""
        channel = await self._get_ticket_channel(ticket["thread_id"])
        if not channel:
            return

        days_inactive = INACTIVE_WARNING_DAYS
        days_until_close = INACTIVE_CLOSE_DAYS - INACTIVE_WARNING_DAYS

        embed = build_inactivity_warning(
            user_id=ticket["user_id"],
            days_inactive=days_inactive,
            days_until_close=days_until_close,
        )

        try:
            await channel.send(embed=embed)
            self.db.mark_ticket_warned(ticket["ticket_id"])
            logger.tree("Inactivity Warning Sent", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Days Inactive", str(days_inactive)),
            ], emoji="⚠️")
        except discord.HTTPException as e:
            log_http_error(e, "Send Inactivity Warning", [
                ("Ticket ID", ticket["ticket_id"]),
            ])

    async def _auto_close_ticket(self: "TicketService", ticket: dict) -> None:
        """Auto-close an inactive ticket."""
        # Use bot as closer
        guild = self.bot.get_guild(self.config.main_guild_id)
        if not guild:
            return

        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member:
            return

        success, _ = await self.close_ticket(
            ticket_id=ticket["ticket_id"],
            closed_by=bot_member,
            reason=f"Automatically closed after {INACTIVE_CLOSE_DAYS} days of inactivity",
        )

        if success:
            logger.tree("Ticket Auto-Closed", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Reason", "Inactivity"),
            ], emoji="🔒")

    async def _auto_delete_ticket(self: "TicketService", ticket: dict) -> None:
        """Auto-delete a closed ticket channel after retention period."""
        ticket_id = ticket["ticket_id"]
        channel_id = ticket["thread_id"]

        # Safety check: only delete if ticket was manually closed by someone
        # This prevents deleting channels for tickets incorrectly marked as closed
        if not ticket.get("closed_by"):
            logger.debug("Skipping Auto-Delete (No Closer)", [
                ("Ticket", ticket_id),
                ("Reason", ticket.get("close_reason", "Unknown")),
            ])
            return

        # Delete the channel
        channel = await self._get_ticket_channel(channel_id)
        if channel:
            try:
                await channel.delete()
            except discord.NotFound:
                pass  # Already deleted
            except discord.HTTPException as e:
                log_http_error(e, "Delete Ticket Channel", [
                    ("Ticket ID", ticket_id),
                ])
                return

        # Delete from database
        self.db.delete_ticket(ticket_id)

        logger.tree("Ticket Auto-Deleted", [
            ("Ticket ID", ticket_id),
            ("Delay", "1 hour after close"),
        ], emoji="🗑️")


__all__ = ["AutoCloseMixin"]
