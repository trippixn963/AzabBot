"""
AzabBot - Helpers Mixin
=======================

Helper methods for channel access, control panel, and scheduling.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord

from src.core.logger import logger
from src.core.constants import THREAD_DELETE_DELAY, QUERY_LIMIT_TINY
from src.utils.retry import safe_fetch_channel
from src.utils.async_utils import create_safe_task

from .embeds import build_control_panel_embed, build_panel_embed
from .views import TicketPanelView, TicketControlPanelView

if TYPE_CHECKING:
    from .service import TicketService


class HelpersMixin:
    """Mixin for ticket helper methods."""

    # =========================================================================
    # Channel Helpers
    # =========================================================================

    async def _get_channel(self: "TicketService") -> Optional[discord.TextChannel]:
        """Get the ticket panel channel with caching."""
        if not self.config.ticket_channel_id:
            logger.debug("Ticket channel ID not configured")
            return None

        # Check cache
        if self._channel and self._channel_cache_time:
            if datetime.now() - self._channel_cache_time < self.CHANNEL_CACHE_TTL:
                return self._channel

        # Fetch channel
        logger.debug("Fetching Ticket Channel", [("ID", str(self.config.ticket_channel_id))])
        channel = await safe_fetch_channel(self.bot, self.config.ticket_channel_id)
        logger.debug("Fetched Channel", [("Channel", str(channel)), ("Type", type(channel).__name__)])

        if channel and isinstance(channel, discord.TextChannel):
            self._channel = channel
            self._channel_cache_time = datetime.now()
            return channel

        logger.warning("Ticket Channel Not a TextChannel", [("Type", type(channel).__name__)])
        return None

    async def _get_ticket_category(
        self: "TicketService",
        guild: discord.Guild
    ) -> Optional[discord.CategoryChannel]:
        """Get the category for creating ticket channels."""
        # Try configured category first
        if self.config.ticket_category_id:
            category = guild.get_channel(self.config.ticket_category_id)
            if isinstance(category, discord.CategoryChannel):
                return category
            else:
                logger.warning("Configured ticket_category_id is not a category", [
                    ("Category ID", str(self.config.ticket_category_id)),
                    ("Guild ID", str(guild.id)),
                ])

        # Fall back to ticket_channel_id's parent category
        panel_channel = await self._get_channel()
        if panel_channel and panel_channel.category:
            return panel_channel.category

        logger.warning("No ticket category found", [
            ("Guild ID", str(guild.id)),
            ("ticket_category_id", str(self.config.ticket_category_id)),
            ("ticket_channel_id", str(self.config.ticket_channel_id)),
        ])
        return None

    async def _get_ticket_channel(
        self: "TicketService",
        channel_id: int
    ) -> Optional[Union[discord.TextChannel, discord.Thread]]:
        """Get a ticket channel with caching (supports both channels and legacy threads)."""
        now = datetime.now()

        # Periodic cache cleanup (every 50 lookups or when cache is large)
        self._cache_lookup_count += 1
        if self._cache_lookup_count >= 50 or len(self._channel_cache_map) > 100:
            self._cleanup_channel_cache(now)
            self._cache_lookup_count = 0

        # Check cache
        if channel_id in self._channel_cache_map:
            channel, cached_at = self._channel_cache_map[channel_id]
            if now - cached_at < self.CHANNEL_CACHE_TTL:
                return channel
            # Expired entry, remove it
            try:
                self._channel_cache_map.pop(channel_id, None)
            except (KeyError, ValueError):
                pass

        # Fetch channel
        try:
            channel = await self.bot.fetch_channel(channel_id)
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                self._channel_cache_map[channel_id] = (channel, now)
                return channel
        except discord.NotFound:
            # Channel deleted, remove from cache
            try:
                self._channel_cache_map.pop(channel_id, None)
            except (KeyError, ValueError):
                pass
        except discord.HTTPException:
            pass

        return None

    def _cleanup_channel_cache(
        self: "TicketService",
        now: Optional[datetime] = None
    ) -> None:
        """Remove expired entries from channel cache."""
        if now is None:
            now = datetime.now()

        expired_keys = [
            channel_id for channel_id, (_, cached_at) in self._channel_cache_map.items()
            if now - cached_at >= self.CHANNEL_CACHE_TTL
        ]
        for key in expired_keys:
            try:
                self._channel_cache_map.pop(key, None)
            except (KeyError, ValueError):
                pass

        if expired_keys:
            logger.debug("Channel Cache Cleanup", [("Expired", str(len(expired_keys)))])

    def has_staff_permission(self: "TicketService", member: discord.Member) -> bool:
        """Check if a member has staff permissions."""
        return member.guild_permissions.manage_messages

    # =========================================================================
    # Staff Permission Management
    # =========================================================================

    async def _lock_out_other_staff(
        self: "TicketService",
        channel: Union[discord.TextChannel, discord.Thread],
        claimer: discord.Member,
        ticket_id: str,
        ticket: Optional[dict] = None,
    ) -> None:
        """Lock out other staff from sending messages (can still view)."""
        guild = channel.guild
        locked_count = 0
        users_to_lock = set()

        # Collect support users
        if self.config.ticket_support_user_ids:
            users_to_lock.update(self.config.ticket_support_user_ids)

        # Collect category-specific assigned user
        if ticket:
            category = ticket.get("category", "support")
            if category == "partnership" and self.config.ticket_partnership_user_id:
                users_to_lock.add(self.config.ticket_partnership_user_id)
            elif category == "suggestion" and self.config.ticket_suggestion_user_id:
                users_to_lock.add(self.config.ticket_suggestion_user_id)

        # Lock out all collected users (except the claimer)
        for uid in users_to_lock:
            if uid == claimer.id:
                continue
            try:
                member = guild.get_member(uid)
                if member:
                    await channel.set_permissions(
                        member,
                        view_channel=True,
                        send_messages=False,
                        attach_files=False,
                        embed_links=False,
                        read_message_history=True,
                    )
                    locked_count += 1
            except discord.HTTPException as e:
                logger.warning("Failed to lock out staff user", [
                    ("Ticket ID", ticket_id),
                    ("User ID", str(uid)),
                    ("Error", str(e)),
                ])

        if locked_count > 0:
            logger.debug("Staff Locked Out", [("Count", str(locked_count)), ("Ticket", ticket_id)])

    async def _restore_staff_access(
        self: "TicketService",
        channel: Union[discord.TextChannel, discord.Thread],
        ticket_id: str,
        ticket: Optional[dict] = None,
    ) -> None:
        """Restore staff access to send messages (when ticket is unclaimed/reopened)."""
        guild = channel.guild
        restored_count = 0
        users_to_restore = set()

        # Collect support users
        if self.config.ticket_support_user_ids:
            users_to_restore.update(self.config.ticket_support_user_ids)

        # Collect category-specific assigned user
        if ticket:
            category = ticket.get("category", "support")
            if category == "partnership" and self.config.ticket_partnership_user_id:
                users_to_restore.add(self.config.ticket_partnership_user_id)
            elif category == "suggestion" and self.config.ticket_suggestion_user_id:
                users_to_restore.add(self.config.ticket_suggestion_user_id)

        # Restore all collected users
        for uid in users_to_restore:
            try:
                member = guild.get_member(uid)
                if member:
                    await channel.set_permissions(
                        member,
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        attach_files=True,
                        embed_links=True,
                        read_message_history=True,
                    )
                    restored_count += 1
            except discord.HTTPException as e:
                logger.warning("Failed to restore staff user permissions", [
                    ("Ticket ID", ticket_id),
                    ("User ID", str(uid)),
                    ("Error", str(e)),
                ])

        if restored_count > 0:
            logger.debug("Staff Access Restored", [("Count", str(restored_count)), ("Ticket", ticket_id)])

    async def _lock_ticket_on_close(
        self: "TicketService",
        channel: Union[discord.TextChannel, discord.Thread],
        ticket: dict,
        guild: discord.Guild,
    ) -> None:
        """Revoke send_messages for ticket opener and any added users when closing.

        Uses a single channel.edit() call to update all permissions at once,
        rather than multiple set_permissions() calls.
        """
        bot_id = self.bot.user.id if self.bot.user else None
        new_overwrites = {}
        locked_count = 0

        # Build new overwrites dict with users locked out
        for target, overwrite in channel.overwrites.items():
            if isinstance(target, discord.Member):
                # Skip the bot itself
                if bot_id and target.id == bot_id:
                    new_overwrites[target] = overwrite
                    continue

                # Skip staff members (they keep full access)
                if self.has_staff_permission(target):
                    new_overwrites[target] = overwrite
                    continue

                # Lock out this user (can view but not send)
                new_overwrites[target] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    attach_files=False,
                    embed_links=False,
                    read_message_history=True,
                )
                locked_count += 1
            else:
                # Keep role overwrites unchanged
                new_overwrites[target] = overwrite

        # Apply all permission changes in a single API call
        if locked_count > 0:
            try:
                await channel.edit(overwrites=new_overwrites)
                logger.debug("Ticket Locked on Close", [("Users", str(locked_count))])
            except discord.HTTPException as e:
                logger.warning("Failed to lock ticket on close", [
                    ("Ticket ID", ticket.get("ticket_id", "unknown")),
                    ("Error", str(e)),
                ])

    # =========================================================================
    # Control Panel Management
    # =========================================================================

    async def _update_control_panel(
        self: "TicketService",
        ticket_id: str,
        channel: Union[discord.TextChannel, discord.Thread],
        closed_by: Optional[discord.Member] = None,
        ticket: Optional[dict] = None,
        ticket_user: Optional[discord.User] = None,
    ) -> None:
        """Update the control panel embed in a ticket channel."""
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
                guild = channel.guild or self.bot.get_guild(self.config.logging_guild_id)
                if guild:
                    closed_by = guild.get_member(ticket["closed_by"])
            except Exception:
                pass

        # Get user ticket count for stats
        user_ticket_count = None
        if ticket_user:
            user_ticket_count = self.db.get_user_ticket_count(ticket["user_id"], ticket["guild_id"])

        # Build new embed and view
        new_embed = build_control_panel_embed(ticket, ticket_user, closed_by, user_ticket_count=user_ticket_count)
        new_view = TicketControlPanelView.from_ticket(ticket)

        # Try to edit existing control panel message
        control_msg_id = ticket.get("control_panel_message_id")
        if control_msg_id:
            try:
                message = await channel.fetch_message(control_msg_id)
                await message.edit(embed=new_embed, view=new_view)
                return
            except discord.NotFound:
                pass
            except discord.HTTPException as e:
                logger.warning("Failed to Edit Control Panel", [("Error", str(e)[:50])])

        # Fallback: find first embed message
        try:
            async for message in channel.history(limit=QUERY_LIMIT_TINY, oldest_first=True):
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
        """Send the ticket creation panel to a channel and store its info."""
        logger.debug("send_panel Called", [("Channel", f"{channel.name} ({channel.id})")])

        embed = build_panel_embed()
        view = TicketPanelView()

        try:
            logger.debug("Sending Ticket Panel Embed")
            message = await channel.send(embed=embed, view=view)
            logger.debug("Panel Message Sent", [("Message ID", str(message.id))])

            # Store panel info in bot_state for recovery
            self.db.set_bot_state("ticket_panel", {
                "message_id": message.id,
                "channel_id": channel.id,
                "guild_id": channel.guild.id,
            })

            logger.tree("Ticket Panel Sent", [
                ("Channel", f"{channel.name} ({channel.id})"),
                ("Message ID", str(message.id)),
            ], emoji="🎫")
            return message
        except discord.HTTPException as e:
            logger.error("Failed to send ticket panel", [
                ("Channel", f"{channel.name} ({channel.id})"),
                ("Error", str(e)),
            ])
            return None
        except Exception as e:
            logger.error("Unexpected error sending ticket panel", [
                ("Channel", f"{channel.name} ({channel.id})"),
                ("Error", str(e)),
            ])
            return None

    async def verify_panel(self: "TicketService") -> None:
        """Verify the ticket panel exists, resend if missing."""
        panel_info = self.db.get_bot_state("ticket_panel")
        logger.debug("Ticket Panel Info from DB", [("Info", str(panel_info)[:50])])

        if not panel_info:
            # No panel stored, send a new one
            logger.tree("Ticket Panel Not Found - Sending New", [
                ("Reason", "No panel info in database"),
            ], emoji="🎫")
            channel = await self._get_channel()
            logger.debug("Got Channel for Panel", [("Channel", str(channel))])
            if channel:
                await self.send_panel(channel)
            else:
                logger.error("Failed to get ticket channel for panel")
            return

        channel_id = panel_info.get("channel_id")
        message_id = panel_info.get("message_id")

        if not channel_id or not message_id:
            # Invalid panel info, send a new one
            channel = await self._get_channel()
            if channel:
                await self.send_panel(channel)
            return

        # Try to fetch the panel message
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)

            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.fetch_message(message_id)
                    logger.debug("Ticket panel verified", [
                        ("Channel", f"{channel.name} ({channel.id})"),
                        ("Message ID", str(message_id)),
                    ])
                except discord.NotFound:
                    # Panel was deleted, resend
                    logger.tree("Ticket Panel Missing - Resending", [
                        ("Channel", f"{channel.name} ({channel.id})"),
                    ], emoji="🎫")
                    await self.send_panel(channel)
        except discord.HTTPException as e:
            logger.error("Failed to verify ticket panel", [("Error", str(e))])

    async def handle_panel_deletion(self: "TicketService", message_id: int) -> None:
        """Handle ticket panel deletion - resend automatically."""
        panel_info = self.db.get_bot_state("ticket_panel")
        if not panel_info:
            return

        if panel_info.get("message_id") != message_id:
            return  # Not the panel message

        channel_id = panel_info.get("channel_id")
        if not channel_id:
            return

        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)

            if channel and isinstance(channel, discord.TextChannel):
                logger.tree("Ticket Panel Deleted - Auto-Resending", [
                    ("Channel", f"{channel.name} ({channel.id})"),
                ], emoji="🎫")
                await self.send_panel(channel)
        except discord.HTTPException as e:
            logger.error("Failed to resend ticket panel", [("Error", str(e))])

    # =========================================================================
    # Channel Deletion
    # =========================================================================

    async def _schedule_channel_deletion(
        self: "TicketService",
        ticket_id: str,
        channel_id: int
    ) -> None:
        """Schedule a ticket channel for deletion after delay."""
        await self._cancel_channel_deletion(ticket_id)

        async def delete_after_delay():
            await asyncio.sleep(THREAD_DELETE_DELAY)
            try:
                channel = await self.bot.fetch_channel(channel_id)
                if isinstance(channel, (discord.TextChannel, discord.Thread)):
                    await channel.delete()
                    logger.debug("Ticket Channel Deleted", [("Ticket", ticket_id)])
            except discord.NotFound:
                pass
            except Exception as e:
                logger.error("Failed to Delete Channel", [("Ticket", ticket_id), ("Error", str(e)[:50])])
            finally:
                async with self._deletions_lock:
                    try:
                        self._pending_deletions.pop(ticket_id, None)
                    except (KeyError, ValueError):
                        pass

        task = create_safe_task(delete_after_delay(), f"Delete channel {ticket_id}")
        async with self._deletions_lock:
            self._pending_deletions[ticket_id] = task

    async def _cancel_channel_deletion(self: "TicketService", ticket_id: str) -> None:
        """Cancel a scheduled channel deletion."""
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
