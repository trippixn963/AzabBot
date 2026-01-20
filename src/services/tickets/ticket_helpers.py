"""
Ticket Service - Helpers Mixin
==============================

Helper methods for channel/thread access, control panel, and scheduling.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.constants import THREAD_DELETE_DELAY
from src.utils.retry import safe_fetch_channel
from src.utils.async_utils import create_safe_task

from .embeds import build_control_panel_embed, build_panel_embed
from .views import TicketPanelView, TicketControlPanelView

if TYPE_CHECKING:
    from .service import TicketService


class HelpersMixin:
    """Mixin for ticket helper methods."""

    # =========================================================================
    # Channel/Thread Helpers
    # =========================================================================

    async def _get_channel(self: "TicketService") -> Optional[discord.TextChannel]:
        """Get the ticket channel with caching."""
        if not self.config.ticket_channel_id:
            return None

        # Check cache
        if self._channel and self._channel_cache_time:
            if datetime.now() - self._channel_cache_time < self.THREAD_CACHE_TTL:
                return self._channel

        # Fetch channel
        channel = await safe_fetch_channel(self.bot, self.config.ticket_channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            self._channel = channel
            self._channel_cache_time = datetime.now()
            return channel

        return None

    async def _get_ticket_thread(
        self: "TicketService",
        thread_id: int
    ) -> Optional[discord.Thread]:
        """Get a ticket thread with caching."""
        now = datetime.now()

        # Periodic cache cleanup (every 50 lookups or when cache is large)
        self._cache_lookup_count += 1
        if self._cache_lookup_count >= 50 or len(self._thread_cache) > 100:
            self._cleanup_thread_cache(now)
            self._cache_lookup_count = 0

        # Check cache
        if thread_id in self._thread_cache:
            thread, cached_at = self._thread_cache[thread_id]
            if now - cached_at < self.THREAD_CACHE_TTL:
                return thread
            # Expired entry, remove it
            self._thread_cache.pop(thread_id, None)

        # Fetch thread
        try:
            thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                self._thread_cache[thread_id] = (thread, now)
                return thread
        except discord.NotFound:
            # Thread deleted, remove from cache
            self._thread_cache.pop(thread_id, None)
        except discord.HTTPException:
            pass

        return None

    def _cleanup_thread_cache(
        self: "TicketService",
        now: Optional[datetime] = None
    ) -> None:
        """Remove expired entries from thread cache."""
        if now is None:
            now = datetime.now()

        expired_keys = [
            thread_id for thread_id, (_, cached_at) in self._thread_cache.items()
            if now - cached_at >= self.THREAD_CACHE_TTL
        ]
        for key in expired_keys:
            self._thread_cache.pop(key, None)

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired thread cache entries")

    def has_staff_permission(self: "TicketService", member: discord.Member) -> bool:
        """Check if a member has staff permissions."""
        return member.guild_permissions.manage_messages

    # =========================================================================
    # Control Panel Management
    # =========================================================================

    async def _update_control_panel(
        self: "TicketService",
        ticket_id: str,
        thread: discord.Thread,
        closed_by: Optional[discord.Member] = None,
        ticket: Optional[dict] = None,
        ticket_user: Optional[discord.User] = None,
    ) -> None:
        """Update the control panel embed in a ticket thread."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return

        # Get ticket user if not passed
        if ticket_user is None:
            try:
                ticket_user = await self.bot.fetch_user(ticket["user_id"])
            except Exception:
                ticket_user = None

        # Get closed_by member if ticket is closed and not passed
        if ticket["status"] == "closed" and not closed_by and ticket.get("closed_by"):
            try:
                guild = thread.guild or self.bot.get_guild(self.config.logging_guild_id)
                if guild:
                    closed_by = guild.get_member(ticket["closed_by"])
            except Exception:
                pass

        # Build new embed and view
        new_embed = build_control_panel_embed(ticket, ticket_user, closed_by)
        new_view = TicketControlPanelView.from_ticket(ticket)

        # Try to edit existing control panel message
        control_msg_id = ticket.get("control_panel_message_id")
        if control_msg_id:
            try:
                message = await thread.fetch_message(control_msg_id)
                await message.edit(embed=new_embed, view=new_view)
                return
            except discord.NotFound:
                pass
            except discord.HTTPException as e:
                logger.warning(f"Failed to edit control panel: {e}")

        # Fallback: find first embed message
        try:
            async for message in thread.history(limit=5, oldest_first=True):
                if message.embeds and "Control Panel" in str(message.embeds[0].title):
                    await message.edit(embed=new_embed, view=new_view)
                    # Update stored message ID
                    self.db.set_control_panel_message(ticket_id, message.id)
                    return
        except discord.HTTPException:
            pass

    # =========================================================================
    # Panel Management
    # =========================================================================

    async def send_panel(
        self: "TicketService",
        channel: discord.TextChannel,
    ) -> Optional[discord.Message]:
        """Send the ticket creation panel to a channel."""
        embed = build_panel_embed()
        view = TicketPanelView()

        try:
            message = await channel.send(embed=embed, view=view)
            logger.tree("Ticket Panel Sent", [
                ("Channel", f"{channel.name} ({channel.id})"),
            ], emoji="🎫")
            return message
        except discord.HTTPException as e:
            logger.error("Failed to send ticket panel", [("Error", str(e))])
            return None

    # =========================================================================
    # Thread Deletion
    # =========================================================================

    async def _schedule_thread_deletion(
        self: "TicketService",
        ticket_id: str,
        thread_id: int
    ) -> None:
        """Schedule a thread for deletion after delay."""
        await self._cancel_thread_deletion(ticket_id)

        async def delete_after_delay():
            await asyncio.sleep(THREAD_DELETE_DELAY)
            try:
                thread = await self.bot.fetch_channel(thread_id)
                if isinstance(thread, discord.Thread):
                    await thread.delete()
                    logger.debug(f"Deleted thread for ticket {ticket_id}")
            except discord.NotFound:
                pass
            except Exception as e:
                logger.error(f"Failed to delete thread: {e}")
            finally:
                async with self._deletions_lock:
                    self._pending_deletions.pop(ticket_id, None)

        task = create_safe_task(delete_after_delay(), f"Delete thread {ticket_id}")
        async with self._deletions_lock:
            self._pending_deletions[ticket_id] = task

    async def _cancel_thread_deletion(self: "TicketService", ticket_id: str) -> None:
        """Cancel a scheduled thread deletion."""
        async with self._deletions_lock:
            task = self._pending_deletions.pop(ticket_id, None)
        if task and not task.done():
            task.cancel()

    # =========================================================================
    # Other Helpers
    # =========================================================================

    def _get_estimated_wait_time(
        self: "TicketService",
        guild_id: int,
        ticket_id: str
    ) -> str:
        """Get estimated wait time text."""
        avg_response = self.db.get_average_response_time(guild_id)
        if avg_response:
            position = self.db.get_open_ticket_position(ticket_id, guild_id)
            if position and position > 1:
                return f"\n\n*Estimated wait: ~{int(avg_response / 60)} minutes (Queue position: #{position})*"
            return f"\n\n*Average response time: ~{int(avg_response / 60)} minutes*"
        return ""


__all__ = ["HelpersMixin"]
